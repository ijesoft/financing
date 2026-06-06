"""
TDD tests for Task A8: post_transaction uses JournalEntry/JournalLine.

Goals:
- post_transaction inserts a row in journal_entries + 2+ journal_lines.
- It does NOT use the orphaned pg_core_models.LedgerEntry table.
- SUM(debit) = SUM(credit) per entry.
- The session passed in is the same one used to commit (real DB, no mocks).
- Bank-grade: multi-leg, integer minor units, idempotency, append-only.
"""
import pytest
import uuid
from decimal import Decimal
from sqlalchemy import select, func

from app.services import accounting_service


@pytest.fixture
async def gl_accounts(db_session):
    """Create two GL accounts to back the journal lines."""
    from app.database.pg_accounting_models import GLAccount
    cash = GLAccount(code="1000-TEST", name="Cash", type="asset")
    revenue = GLAccount(code="4000-TEST", name="Revenue", type="income")
    db_session.add_all([cash, revenue])
    await db_session.commit()
    return cash, revenue


@pytest.mark.asyncio
async def test_post_transaction_inserts_journal_entry_and_lines(db_session, gl_accounts):
    """post_transaction must insert one JournalEntry + two JournalLines."""
    from app.database.pg_accounting_models import JournalEntry, JournalLine

    je_id = await accounting_service.post_transaction(
        db_session,
        legs=[
            {"account_code": "1000-TEST", "debit_minor": 25000, "credit_minor": 0},
            {"account_code": "4000-TEST", "debit_minor": 0, "credit_minor": 25000},
        ],
        idempotency_key=f"A8-{uuid.uuid4()}",
    )
    assert je_id > 0

    je_rows = (await db_session.execute(select(JournalEntry))).scalars().all()
    assert len(je_rows) >= 1

    jl_rows = (await db_session.execute(select(JournalLine).filter(JournalLine.entry_id == je_id))).scalars().all()
    assert len(jl_rows) == 2, f"Expected 2 journal lines, got {len(jl_rows)}"

    d = sum(Decimal(str(l.debit or 0)) for l in jl_rows)
    c = sum(Decimal(str(l.credit or 0)) for l in jl_rows)
    assert d == c, f"Unbalanced entry {je_id}: debit={d} credit={c}"
    assert d == Decimal("250.00")


@pytest.mark.asyncio
async def test_post_transaction_does_not_touch_ledger_entries_table(db_session, gl_accounts):
    """post_transaction must not write to the orphaned `ledger_entries` table."""
    from sqlalchemy import text

    await accounting_service.post_transaction(
        db_session,
        legs=[
            {"account_code": "1000-TEST", "debit_minor": 9999, "credit_minor": 0},
            {"account_code": "4000-TEST", "debit_minor": 0, "credit_minor": 9999},
        ],
        idempotency_key=f"A8B-{uuid.uuid4()}",
    )
    try:
        result = await db_session.execute(text("SELECT COUNT(*) FROM ledger_entries"))
        n = result.scalar() or 0
    except Exception:
        n = 0
    assert n == 0, f"ledger_entries table should be untouched, got {n} rows"


@pytest.mark.asyncio
async def test_post_transaction_rejects_zero_or_negative(db_session, gl_accounts):
    """Sum of legs must be > 0."""
    with pytest.raises(ValueError):
        await accounting_service.post_transaction(
            db_session,
            legs=[
                {"account_code": "1000-TEST", "debit_minor": 0, "credit_minor": 0},
                {"account_code": "4000-TEST", "debit_minor": 0, "credit_minor": 0},
            ],
        )
    with pytest.raises(ValueError):
        await accounting_service.post_transaction(
            db_session,
            legs=[
                {"account_code": "1000-TEST", "debit_minor": -1, "credit_minor": 0},
                {"account_code": "4000-TEST", "debit_minor": 0, "credit_minor": -1},
            ],
        )
