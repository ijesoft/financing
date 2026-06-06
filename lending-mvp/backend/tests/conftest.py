"""
Pytest configuration and fixtures for Phase 2.1 e2e tests.

This configuration sets up the PostgreSQL database for testing and provides
fixtures for database sessions, test data, and cleanup.
"""

import pytest
import pytest_asyncio
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from decimal import Decimal

from app.config import settings
from app.database.pg_models import Base
from app.database.pg_loan_models import PGLoanProduct


# Create a separate test database URL - use localhost with correct port
TEST_DATABASE_URL = "postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_test_db"

# Force settings to use the async-compatible test URL. This prevents
# `app.database.postgres` (and any module that eagerly creates an engine
# at import time) from blowing up with "psycopg2 is not async" because
# the developer's .env points at a sync driver.
settings.database_url = TEST_DATABASE_URL


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a test database engine for each test function."""
    # Create engine with echo=False for cleaner output
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS value_date DATE",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS branch_id BIGINT",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS branch_code VARCHAR(20)",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS loan_id BIGINT",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS customer_id VARCHAR(64)",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64)",
            "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS row_hash VARCHAR(64) NOT NULL DEFAULT ''",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_journal_entries_idem ON journal_entries (idempotency_key) WHERE idempotency_key IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS ix_journal_entries_loan ON journal_entries (loan_id)",
            "CREATE INDEX IF NOT EXISTS ix_journal_entries_branch ON journal_entries (branch_code)",
            "CREATE INDEX IF NOT EXISTS ix_journal_entries_value_date ON journal_entries (value_date)",
            "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS is_npl BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS non_accrual_since TIMESTAMPTZ",
            "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS collections_officer VARCHAR(64)",
            "ALTER TABLE loan_applications ADD COLUMN IF NOT EXISTS ecl_stage VARCHAR(10) DEFAULT 'S1'",
            "CREATE INDEX IF NOT EXISTS ix_loan_applications_npl ON loan_applications (is_npl) WHERE is_npl = TRUE",
            "CREATE INDEX IF NOT EXISTS ix_loan_applications_branch_status ON loan_applications (branch_code, status)",
            "CREATE INDEX IF NOT EXISTS ix_amort_sched_loan_due ON amortization_schedules (loan_id, due_date)",
            "CREATE INDEX IF NOT EXISTS ix_amort_sched_unpaid ON amortization_schedules (loan_id, due_date) WHERE status IN ('pending', 'partial', 'overdue')",
            "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        ]:
            await conn.execute(text(stmt))

        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION deny_journal_mutations()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'UPDATE'
                   AND TG_TABLE_NAME = 'journal_entries'
                   AND OLD.row_hash = ''
                   AND NEW.row_hash <> ''
                   AND NEW.reference_no = OLD.reference_no
                   AND NEW.description IS NOT DISTINCT FROM OLD.description
                   AND NEW.created_by IS NOT DISTINCT FROM OLD.created_by
                   AND NEW.value_date IS NOT DISTINCT FROM OLD.value_date
                   AND NEW.branch_id IS NOT DISTINCT FROM OLD.branch_id
                   AND NEW.branch_code IS NOT DISTINCT FROM OLD.branch_code
                   AND NEW.idempotency_key IS NOT DISTINCT FROM OLD.idempotency_key
                   AND NEW.loan_id IS NOT DISTINCT FROM OLD.loan_id
                   AND NEW.customer_id IS NOT DISTINCT FROM OLD.customer_id
                   AND NEW.prev_hash IS NOT DISTINCT FROM OLD.prev_hash
                THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'journal_entries and journal_lines are append-only. Use compensating entries for corrections.';
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION check_journal_balanced()
            RETURNS trigger AS $$
            DECLARE
                total_dr NUMERIC;
                total_cr NUMERIC;
            BEGIN
                SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
                INTO total_dr, total_cr
                FROM journal_lines
                WHERE entry_id = NEW.entry_id;
                IF total_dr <> total_cr THEN
                    RAISE EXCEPTION 'Journal entry % unbalanced: Dr=% Cr=%', NEW.entry_id, total_dr, total_cr;
                END IF;
                IF total_dr = 0 THEN
                    RAISE EXCEPTION 'Journal entry % is empty', NEW.entry_id;
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION verify_journal_hash_chain()
            RETURNS TABLE(entry_id BIGINT, valid BOOLEAN, computed_hash VARCHAR) AS $$
            DECLARE
                rec RECORD;
                prev VARCHAR(64) := '';
                expected VARCHAR(64);
                payload JSON;
            BEGIN
                FOR rec IN
                    SELECT je.id, je.prev_hash, je.row_hash, je.timestamp,
                           COALESCE(json_agg(json_build_object(
                               'account_code', jl.account_code,
                               'debit_minor', (jl.debit * 100)::bigint,
                               'credit_minor', (jl.credit * 100)::bigint
                           ) ORDER BY jl.account_code) FILTER (WHERE jl.id IS NOT NULL), '[]'::json) AS lines_json
                    FROM journal_entries je
                    LEFT JOIN journal_lines jl ON jl.entry_id = je.id
                    GROUP BY je.id, je.prev_hash, je.row_hash, je.timestamp
                    ORDER BY je.id ASC
                LOOP
                    payload := json_build_object(
                        'entry_id', rec.id,
                        'ts', rec.timestamp,
                        'lines', rec.lines_json
                    );
                    expected := encode(digest(prev || payload::text, 'sha256'), 'hex');
                    entry_id := rec.id;
                    computed_hash := expected;
                    valid := (expected = rec.row_hash) AND (COALESCE(rec.prev_hash, '') = prev);
                    RETURN NEXT;
                    prev := rec.row_hash;
                END LOOP;
            END;
            $$ LANGUAGE plpgsql;
        """))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_journal_entries_no_update ON journal_entries"))
        await conn.execute(text("CREATE TRIGGER trg_journal_entries_no_update BEFORE UPDATE OR DELETE ON journal_entries FOR EACH ROW EXECUTE FUNCTION deny_journal_mutations()"))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_journal_lines_no_update ON journal_lines"))
        await conn.execute(text("CREATE TRIGGER trg_journal_lines_no_update BEFORE UPDATE OR DELETE ON journal_lines FOR EACH ROW EXECUTE FUNCTION deny_journal_mutations()"))
        await conn.execute(text("DROP TRIGGER IF EXISTS trg_journal_lines_balanced ON journal_lines"))
        await conn.execute(text("CREATE CONSTRAINT TRIGGER trg_journal_lines_balanced AFTER INSERT ON journal_lines DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_journal_balanced()"))

    yield engine

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except RuntimeError:
        pass

    try:
        await engine.dispose()
    except RuntimeError:
        pass


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """Create a test database session for each test function."""
    # Create async session
    async_session = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def clean_database(db_session: AsyncSession):
    """Helper fixture to ensure database is clean before each test."""
    # Delete all loan products to start clean
    await db_session.execute(
        text("DELETE FROM loan_products")
    )
    await db_session.flush()
    yield db_session


@pytest.fixture
def sample_loan_product_data():
    """Provide sample data for loan product tests."""
    return {
        "product_code": "TEST_001",
        "name": "Test Loan Product",
        "amortization_type": "declining_balance",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("5.5"),
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 1,
        "is_active": True,
    }


@pytest.fixture
def sample_flat_rate_product():
    """Provide sample data for flat rate loan product."""
    return {
        "product_code": "FLAT_001",
        "name": "Flat Rate Personal Loan",
        "amortization_type": "flat_rate",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("5.0"),
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 0,
        "is_active": True,
    }


@pytest.fixture
def sample_balloon_product():
    """Provide sample data for balloon payment loan product."""
    return {
        "product_code": "BALLOON_001",
        "name": "Balloon Payment Equipment Loan",
        "amortization_type": "balloon_payment",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("4.0"),
        "penalty_rate": Decimal("3.0"),
        "grace_period_months": 2,
        "is_active": True,
    }


@pytest.fixture
def sample_interest_only_product():
    """Provide sample data for interest-only loan product."""
    return {
        "product_code": "INT_ONLY_001",
        "name": "Interest-Only Business Loan",
        "amortization_type": "interest_only",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("6.0"),
        "penalty_rate": Decimal("2.5"),
        "grace_period_months": 3,
        "is_active": True,
    }


@pytest.fixture
def sample_prepayment_allowed_product():
    """Provide sample data for prepayment allowed loan product."""
    return {
        "product_code": "PREPAY_001",
        "name": "Prepayment Allowed Loan",
        "amortization_type": "declining_balance",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("5.5"),
        "prepayment_allowed": True,
        "prepayment_penalty_rate": Decimal("0.0"),
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 1,
        "is_active": True,
    }


@pytest.fixture
def sample_prepayment_restricted_product():
    """Provide sample data for prepayment restricted loan product."""
    return {
        "product_code": "PREPAY_RESTRICT_001",
        "name": "Restricted Prepayment Loan",
        "amortization_type": "interest_only",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("4.5"),
        "prepayment_allowed": False,
        "prepayment_penalty_rate": Decimal("3.0"),
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 2,
        "is_active": True,
    }


@pytest.fixture
def sample_origination_fee_product():
    """Provide sample data for loan product with origination fee."""
    return {
        "product_code": "ORIGIN_001",
        "name": "Origination Fee Loan",
        "amortization_type": "declining_balance",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("6.0"),
        "origination_fee_rate": Decimal("1.5"),
        "origination_fee_type": "upfront",
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 1,
        "is_active": True,
    }


@pytest.fixture
def sample_loan_limit_product():
    """Provide sample data for loan product with customer limit."""
    return {
        "product_code": "LIMIT_001",
        "name": "Limited Loan Product",
        "amortization_type": "flat_rate",
        "repayment_frequency": "monthly",
        "interest_rate": Decimal("6.0"),
        "customer_loan_limit": Decimal("100000"),
        "penalty_rate": Decimal("2.0"),
        "grace_period_months": 1,
        "is_active": True,
    }
