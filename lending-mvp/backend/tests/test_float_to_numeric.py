"""
Regression test for Float→Numeric migration on money columns.

Bug: `aml_alerts.ctr_amount` and `collections.amount` are stored as
`double precision` (Float). Money must be stored as `numeric(15,2)` to
avoid precision loss. This test:

  1. Asserts the columns are numeric(15,2) after migration.
  2. Inserts a row with `Decimal('500000.00')` and reads it back losslessly.
  3. Inserts with `Decimal('500000.005')` and asserts it rounds to the
     chosen scale (numeric(15,2) → 500000.01 by default rounding).
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


TEST_DATABASE_URL = "postgresql+asyncpg://lending_user:lending_secret@localhost:5433/lending_test_db"
SYNC_TEST_DATABASE_URL = "postgresql+psycopg2://lending_user:lending_secret@localhost:5433/lending_test_db"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _run_alembic_upgrade():
    """Synchronously run `alembic upgrade head` against the test database.

    Uses sync psycopg2 (env.py swaps asyncpg → psycopg2 internally).
    env.py reads DATABASE_URL from os.environ, so we set it here.
    """
    from alembic.config import Config
    from alembic import command

    # env.py reads DATABASE_URL from environment
    os.environ["DATABASE_URL"] = SYNC_TEST_DATABASE_URL
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", SYNC_TEST_DATABASE_URL)
    cfg.attributes["pytest_testing"] = True
    command.upgrade(cfg, "head")


@pytest.fixture(scope="module", autouse=True)
def _alembic_applied():
    """Apply all migrations once per module, after wiping the schema."""
    from sqlalchemy import create_engine
    eng = create_engine(SYNC_TEST_DATABASE_URL)
    with eng.begin() as conn:
        # Force-disconnect any leftover sessions, then drop & recreate
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid()
                """
            )
        )
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    eng.dispose()
    _run_alembic_upgrade()
    # Some Phase 1 tables (aml_alerts, pep_records) are not yet represented
    # in the migration history — they are normally created by the app's
    # Base.metadata.create_all at startup. We mirror that here so the test
    # can exercise the data type on a real column.
    from app.database.pg_models import Base
    eng2 = create_engine(SYNC_TEST_DATABASE_URL)
    Base.metadata.create_all(eng2)
    eng2.dispose()
    yield


@pytest.mark.asyncio
async def test_aml_alerts_ctr_amount_is_numeric():
    """aml_alerts.ctr_amount must be numeric(15,2), not double precision."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT data_type, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_name = 'aml_alerts' AND column_name = 'ctr_amount'
                """
            )
        )
        row = result.fetchone()
        assert row is not None, "aml_alerts.ctr_amount column does not exist"
        data_type, precision, scale = row
        assert data_type == "numeric", (
            f"aml_alerts.ctr_amount must be numeric, got {data_type}"
        )
        assert precision == 15, f"expected precision 15, got {precision}"
        assert scale == 2, f"expected scale 2, got {scale}"
    await engine.dispose()


@pytest.mark.asyncio
async def test_collections_amount_is_numeric():
    """collections.amount must be numeric(15,2), not double precision."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT data_type, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_name = 'collections' AND column_name = 'amount'
                """
            )
        )
        row = result.fetchone()
        assert row is not None, "collections.amount column does not exist"
        data_type, precision, scale = row
        assert data_type == "numeric", (
            f"collections.amount must be numeric, got {data_type}"
        )
        assert precision == 15, f"expected precision 15, got {precision}"
        assert scale == 2, f"expected scale 2, got {scale}"
    await engine.dispose()


@pytest.mark.asyncio
async def test_aml_alerts_ctr_amount_round_trip():
    """Inserting Decimal('500000.00') must round-trip without precision loss."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO aml_alerts
                  (customer_id, alert_type, severity, status, requires_filing, ctr_amount)
                VALUES
                  (:cid, 'ctr', 'low', 'pending_review', false, :amt)
                """
            ),
            {"cid": "CUST-001", "amt": Decimal("500000.00")},
        )
        result = await conn.execute(
            text("SELECT ctr_amount FROM aml_alerts WHERE customer_id = :cid"),
            {"cid": "CUST-001"},
        )
        row = result.fetchone()
        assert row is not None
        read_back = row[0]
        assert Decimal(read_back) == Decimal("500000.00"), (
            f"expected 500000.00, got {read_back!r}"
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_collections_amount_round_trip():
    """Inserting Decimal('500000.005') must round to scale 2 (500000.01)."""
    from datetime import datetime, timezone
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        now = datetime.now(timezone.utc)
        await conn.execute(
            text(
                """
                INSERT INTO collections
                  (customer_id, amount, status, due_date, created_at, updated_at)
                VALUES
                  (:cid, :amt, 'pending', :dd, :ts, :ts)
                """
            ),
            {"cid": "CUST-002", "amt": Decimal("500000.005"), "dd": now, "ts": now},
        )
        result = await conn.execute(
            text("SELECT amount FROM collections WHERE customer_id = :cid"),
            {"cid": "CUST-002"},
        )
        row = result.fetchone()
        assert row is not None
        read_back = row[0]
        assert Decimal(read_back) == Decimal("500000.01"), (
            f"expected 500000.01 after rounding, got {read_back!r}"
        )
    await engine.dispose()
