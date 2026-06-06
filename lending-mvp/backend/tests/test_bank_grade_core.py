"""
BE-01..BE-05: bank-grade accounting core tests.
"""
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.accounting import create_journal_entry, _to_minor, _normalize_line
from app.database.pg_accounting_models import (
    GLAccount,
    JournalEntry,
    JournalLine,
    TransactionIdempotency,
)
from app.services.accounting_service import post_transaction


@pytest.mark.asyncio
async def test_be01_rejects_float_amount(db_session):
    with pytest.raises(TypeError):
        _to_minor(100.5, "debit_minor")


@pytest.mark.asyncio
async def test_be01_accepts_int_and_decimal(db_session):
    assert _to_minor(100, "debit_minor") == 100
    assert _to_minor(Decimal("100.50"), "debit_minor") == 10050


@pytest.mark.asyncio
async def test_be01_rejects_negative_amount(db_session):
    with pytest.raises(ValueError):
        _normalize_line({"account_code": "1200", "debit_minor": -10, "credit_minor": 0})


@pytest.mark.asyncio
async def test_be01_rejects_both_sides_set(db_session):
    with pytest.raises(ValueError):
        _normalize_line({"account_code": "1200", "debit_minor": 10, "credit_minor": 10})


@pytest.mark.asyncio
async def test_be02_multi_leg_balanced(db_session):
    je_id = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 100000, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 80000},
            {"account_code": "4100", "debit_minor": 0, "credit_minor": 20000},
        ],
        description="Test multi-leg",
        idempotency_key=f"BE02-{uuid.uuid4()}",
    )
    assert je_id > 0
    result = await db_session.execute(
        text("SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0) FROM journal_lines WHERE entry_id=:i"),
        {"i": je_id},
    )
    dr, cr = result.one()
    assert Decimal(dr) == Decimal(cr)


@pytest.mark.asyncio
async def test_be02_rejects_unbalanced(db_session):
    with pytest.raises(ValueError):
        await post_transaction(
            db_session,
            legs=[
                {"account_code": "1010", "debit_minor": 100000, "credit_minor": 0},
                {"account_code": "1200", "debit_minor": 0, "credit_minor": 99999},
            ],
            description="intentional imbalance",
            idempotency_key=f"BE02B-{uuid.uuid4()}",
        )


@pytest.mark.asyncio
async def test_be02_requires_minimum_two_legs(db_session):
    with pytest.raises(ValueError):
        await post_transaction(
            db_session,
            legs=[{"account_code": "1010", "debit_minor": 100, "credit_minor": 0}],
            description="only one leg",
        )


@pytest.mark.asyncio
async def test_be03_idempotency_same_key_returns_same_entry(db_session):
    key = f"BE03-{uuid.uuid4()}"
    je_id_1 = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 50000, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 50000},
        ],
        description="First post",
        idempotency_key=key,
    )
    je_id_2 = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 50000, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 50000},
        ],
        description="Replay with same key",
        idempotency_key=key,
    )
    assert je_id_1 == je_id_2


@pytest.mark.asyncio
async def test_be04_append_only_rejects_update(db_session):
    je_id = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 100, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 100},
        ],
        description="append-only probe",
        idempotency_key=f"BE04-{uuid.uuid4()}",
    )
    with pytest.raises(Exception) as exc:
        await db_session.execute(
            text("UPDATE journal_entries SET description='hacked' WHERE id=:i"),
            {"i": je_id},
        )
    msg = str(exc.value).lower()
    assert "append-only" in msg or "deny" in msg or "mutation" in msg


@pytest.mark.asyncio
async def test_be04_append_only_rejects_delete(db_session):
    je_id = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 100, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 100},
        ],
        description="append-only delete probe",
        idempotency_key=f"BE04D-{uuid.uuid4()}",
    )
    with pytest.raises(Exception) as exc:
        await db_session.execute(
            text("DELETE FROM journal_entries WHERE id=:i"),
            {"i": je_id},
        )
    msg = str(exc.value).lower()
    assert "append-only" in msg or "deny" in msg or "mutation" in msg


@pytest.mark.asyncio
async def test_be05_hash_chain_set_on_entry(db_session):
    je_id = await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 700, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 700},
        ],
        description="hash chain",
        idempotency_key=f"BE05-{uuid.uuid4()}",
    )
    result = await db_session.execute(
        text("SELECT prev_hash, row_hash FROM journal_entries WHERE id=:i"),
        {"i": je_id},
    )
    prev_hash, row_hash = result.one()
    assert row_hash and len(row_hash) == 64
    if je_id > 1:
        assert prev_hash and len(prev_hash) == 64


@pytest.mark.asyncio
async def test_be05_verify_chain_function(db_session):
    await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 100, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 100},
        ],
        description="chain verify 1",
        idempotency_key=f"BE05V-{uuid.uuid4()}",
    )
    await post_transaction(
        db_session,
        legs=[
            {"account_code": "1010", "debit_minor": 200, "credit_minor": 0},
            {"account_code": "1200", "debit_minor": 0, "credit_minor": 200},
        ],
        description="chain verify 2",
        idempotency_key=f"BE05V-{uuid.uuid4()}",
    )
    result = await db_session.execute(
        text("SELECT entry_id, valid, computed_hash FROM verify_journal_hash_chain()")
    )
    rows = result.all()
    assert len(rows) >= 2
    for r in rows:
        assert r.computed_hash and len(r.computed_hash) == 64
