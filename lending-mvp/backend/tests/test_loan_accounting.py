"""
BE-06, BE-07: loan disbursement + repayment posting.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.loan_accounting_service import (
    post_loan_disbursement,
    post_loan_repayment,
)


@pytest.mark.asyncio
async def test_be06_disbursement_posting(db_session):
    je_id = await post_loan_disbursement(
        db_session,
        loan_id=1,
        principal_minor=1000000,
        net_disbursement_minor=985000,
        origination_fee_minor=15000,
        customer_id="CUST-001",
        branch_code="HQ",
        idempotency_key=f"BE06-{uuid.uuid4()}",
    )
    result = await db_session.execute(
        text(
            "SELECT account_code, debit, credit FROM journal_lines "
            "WHERE entry_id=:i ORDER BY account_code"
        ),
        {"i": je_id},
    )
    rows = result.all()
    by_acct = {r.account_code: (Decimal(r.debit or 0), Decimal(r.credit or 0)) for r in rows}
    assert by_acct["1010"][1] == Decimal("9850.00")
    assert by_acct["1200"][0] == Decimal("10000.00")
    assert by_acct["4200"][1] == Decimal("150.00")
    dr = sum((d for d, _ in by_acct.values()), Decimal(0))
    cr = sum((c for _, c in by_acct.values()), Decimal(0))
    assert dr == cr


@pytest.mark.asyncio
async def test_be07_repayment_waterfall_posting(db_session):
    je_id = await post_loan_repayment(
        db_session,
        loan_id=2,
        total_minor=100000,
        penalty_minor=20000,
        fee_minor=10000,
        interest_minor=30000,
        principal_minor=40000,
        overpayment_minor=0,
        customer_id="CUST-002",
        branch_code="HQ",
        idempotency_key=f"BE07-{uuid.uuid4()}",
    )
    result = await db_session.execute(
        text("SELECT account_code, debit, credit FROM journal_lines WHERE entry_id=:i"),
        {"i": je_id},
    )
    rows = result.all()
    by_acct = {r.account_code: (Decimal(r.debit or 0), Decimal(r.credit or 0)) for r in rows}
    assert by_acct["1010"][0] == Decimal("1000.00")
    assert by_acct["1200"][1] == Decimal("400.00")
    assert by_acct["4100"][1] == Decimal("300.00")
    assert by_acct["4200"][1] == Decimal("100.00")
    assert by_acct["4300"][1] == Decimal("200.00")
    dr = sum((d for d, _ in by_acct.values()), Decimal(0))
    cr = sum((c for _, c in by_acct.values()), Decimal(0))
    assert dr == cr


@pytest.mark.asyncio
async def test_be07_repayment_with_overpayment(db_session):
    je_id = await post_loan_repayment(
        db_session,
        loan_id=3,
        total_minor=150000,
        penalty_minor=0,
        fee_minor=0,
        interest_minor=0,
        principal_minor=100000,
        overpayment_minor=50000,
        customer_id="CUST-003",
        branch_code="HQ",
        idempotency_key=f"BE07O-{uuid.uuid4()}",
    )
    result = await db_session.execute(
        text("SELECT account_code, credit FROM journal_lines WHERE entry_id=:i AND account_code='2100'"),
        {"i": je_id},
    )
    row = result.first()
    assert row is not None
    assert Decimal(row.credit) == Decimal("500.00")


@pytest.mark.asyncio
async def test_be07_rejects_allocation_mismatch(db_session):
    with pytest.raises(ValueError):
        await post_loan_repayment(
            db_session,
            loan_id=4,
            total_minor=100000,
            penalty_minor=0,
            fee_minor=0,
            interest_minor=0,
            principal_minor=90000,
            overpayment_minor=0,
            customer_id="CUST-004",
            branch_code="HQ",
            idempotency_key=f"BE07X-{uuid.uuid4()}",
        )


@pytest.mark.asyncio
async def test_be06_rejects_zero_principal(db_session):
    with pytest.raises(ValueError):
        await post_loan_disbursement(
            db_session,
            loan_id=5,
            principal_minor=0,
            net_disbursement_minor=0,
            customer_id="CUST-005",
            branch_code="HQ",
            idempotency_key=f"BE06Z-{uuid.uuid4()}",
        )
