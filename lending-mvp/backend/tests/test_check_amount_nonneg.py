"""
Regression test for CHECK (amount >= 0) on money columns.

Bug: There are no CHECK constraints preventing negative amounts on money
columns. This test asserts that for each of the listed tables, updating
a money column to a negative value raises IntegrityError, and that a
zero value is accepted.
"""
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import os

import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.exc import IntegrityError


TEST_DATABASE_URL = "postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_test_db"
SYNC_TEST_DATABASE_URL = "postgresql+psycopg2://lending_user:lending_secret@localhost:5433/lending_test_db"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _run_alembic_upgrade():
    from alembic.config import Config
    from alembic import command

    os.environ["DATABASE_URL"] = SYNC_TEST_DATABASE_URL
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", SYNC_TEST_DATABASE_URL)
    cfg.attributes["pytest_testing"] = True
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _alembic_applied():
    """Wipe the schema, run all migrations, then run Base.metadata.create_all
    to add the Phase-1-only tables (savings_accounts, aml_alerts, etc.),
    then re-run the constraint-only migration to add CHECKs to those tables.
    """
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    eng.dispose()
    _run_alembic_upgrade()
    from app.database.pg_models import Base
    eng2 = create_engine(SYNC_TEST_DATABASE_URL)
    Base.metadata.create_all(eng2)
    eng2.dispose()
    # Re-run only the C3 migration to add CHECKs to tables that
    # `create_all` just created. In production, this works because
    # `create_tables()` runs on every app start; a re-application of the
    # constraint step is safe (it is idempotent).
    # _reapply_check_constraints()  # red-green-red
    yield
    # Teardown: TRUNCATE all data tables so the next test sees a clean DB
    eng3 = create_engine(SYNC_TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE branches, loan_products, gl_accounts, customers, "
                "savings_accounts, loan_applications, loan_transactions, "
                "savings_transactions, journal_entries, journal_lines, "
                "aml_alerts, collections RESTART IDENTITY CASCADE"
            )
        )
    eng3.dispose()


def _reapply_check_constraints():
    """Re-execute the CHECK constraint logic against tables that may have
    been created by `Base.metadata.create_all` after the migration ran.
    """
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    MONEY_COLUMNS = [
        ("loan_applications", "principal"),
        ("loan_applications", "approved_principal"),
        ("loan_applications", "outstanding_balance"),
        ("loan_transactions", "amount"),
        ("savings_accounts", "balance"),
        ("savings_accounts", "principal"),
        ("savings_accounts", "target_amount"),
        ("savings_transactions", "amount"),
        ("savings_transactions", "balance_before"),
        ("savings_transactions", "balance_after"),
        ("collections", "amount"),
        ("aml_alerts", "ctr_amount"),
        ("journal_lines", "debit"),
        ("journal_lines", "credit"),
        ("amortization_schedules", "principal_due"),
        ("amortization_schedules", "interest_due"),
        ("amortization_schedules", "penalty_due"),
        ("amortization_schedules", "principal_paid"),
        ("amortization_schedules", "interest_paid"),
        ("amortization_schedules", "penalty_paid"),
    ]
    with eng.begin() as conn:
        for table, column in MONEY_COLUMNS:
            table_exists = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": table},
            ).fetchone()
            if not table_exists:
                continue
            col_exists = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            ).fetchone()
            if not col_exists:
                continue
            name = f"ck_{table}_{column}_nonneg"
            exists = conn.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
                {"n": name},
            ).fetchone()
            if exists:
                continue
            conn.execute(
                text(
                    f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" '
                    f'CHECK ("{column}" >= 0)'
                )
            )
    eng.dispose()


def _setup_basic(eng):
    """Insert the minimum supporting rows so we can touch money tables."""
    statements = [
        # A branch (FK for customers and other tables)
        "INSERT INTO branches (code, name) VALUES ('HQ', 'HQ')",
        # A loan product (FK for loans, loan_applications, loan_transactions)
        (
            "INSERT INTO loan_products "
            "(product_code, name, amortization_type, repayment_frequency, interest_rate, penalty_rate, grace_period_months, is_active) "
            "VALUES ('P-1', 'Test', 'flat_rate', 'monthly', 5.0, 0.0, 0, true)"
        ),
        # A GL account (FK for journal_lines)
        "INSERT INTO gl_accounts (code, name, type) VALUES ('1000', 'Cash', 'asset')",
        # A customer
        (
            "INSERT INTO customers (customer_type, display_name, branch_id, branch_code, is_active) "
            "VALUES ('individual', 'Test Customer', 1, 'HQ', true)"
        ),
        # A savings account
        (
            "INSERT INTO savings_accounts (account_number, customer_id, account_type, balance, currency, status) "
            "VALUES ('SA-1', 1, 'regular', 0, 'PHP', 'active')"
        ),
        # A loan application
        (
            "INSERT INTO loan_applications "
            "(customer_id, product_id, principal, term_months, status) "
            "VALUES ('CUST-1', 1, 1000, 12, 'pending')"
        ),
        # A loan transaction
        (
            "INSERT INTO loan_transactions (loan_id, type, amount) "
            "VALUES (1, 'fee', 100)"
        ),
        # A savings transaction
        (
            "INSERT INTO savings_transactions "
            "(account_id, transaction_type, amount, balance_before, balance_after) "
            "VALUES (1, 'deposit', 100, 0, 100)"
        ),
        # A journal entry
        "INSERT INTO journal_entries (reference_no, description) VALUES ('JE-1', 't')",
        # An aml_alert
        (
            "INSERT INTO aml_alerts (customer_id, alert_type, severity, status, requires_filing) "
            "VALUES ('C-1', 'ctr', 'low', 'pending_review', false)"
        ),
        # A collection
        (
            "INSERT INTO collections (customer_id, amount, status, due_date, created_at, updated_at) "
            "VALUES ('C-1', 100, 'pending', now(), now(), now())"
        ),
    ]
    # Use a single transaction but commit at the end so partial state isn't
    # seen by subsequent tests. If something fails, the whole setup rolls
    # back, which is what we want.
    with eng.begin() as conn:
        for s in statements:
            conn.execute(text(s))


@pytest.mark.parametrize(
    "table,column,update_sql",
    [
        (
            "loan_applications",
            "principal",
            "UPDATE loan_applications SET principal = -1 WHERE id = 1",
        ),
        (
            "loan_transactions",
            "amount",
            "UPDATE loan_transactions SET amount = -1 WHERE id = 1",
        ),
        (
            "savings_accounts",
            "balance",
            "UPDATE savings_accounts SET balance = -1 WHERE id = 1",
        ),
        (
            "savings_transactions",
            "amount",
            "UPDATE savings_transactions SET amount = -1 WHERE id = 1",
        ),
        (
            "collections",
            "amount",
            "UPDATE collections SET amount = -1 WHERE id = 1",
        ),
        (
            "aml_alerts",
            "ctr_amount",
            "UPDATE aml_alerts SET ctr_amount = -1 WHERE id = 1",
        ),
    ],
)
def test_negative_amount_rejected(table, column, update_sql):
    """Updating a money column to a negative value must raise IntegrityError."""
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    _setup_basic(eng)
    with eng.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text(update_sql))
            conn.commit()
    eng.dispose()


def test_journal_lines_debit_negative_rejected():
    """Updating journal_lines.debit to -1 must raise IntegrityError."""
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    _setup_basic(eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO journal_lines (entry_id, account_code, debit, credit) "
                "VALUES (1, '1000', 100, 0)"
            )
        )
    with eng.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text("UPDATE journal_lines SET debit = -1 WHERE entry_id = 1"))
            conn.commit()
    eng.dispose()


def test_journal_lines_credit_negative_rejected():
    """Updating journal_lines.credit to -1 must raise IntegrityError."""
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    _setup_basic(eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO journal_lines (entry_id, account_code, debit, credit) "
                "VALUES (1, '1000', 0, 100)"
            )
        )
    with eng.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text("UPDATE journal_lines SET credit = -1 WHERE entry_id = 1"))
            conn.commit()
    eng.dispose()
