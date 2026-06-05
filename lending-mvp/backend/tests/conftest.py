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
from sqlalchemy.pool import StaticPool
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
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


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
