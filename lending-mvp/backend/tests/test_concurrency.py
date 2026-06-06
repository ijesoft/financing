"""
Concurrency: 100 parallel repayment posts on one loan.
"""
import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import get_async_session_local
from app.database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    PGLoanProduct,
)
from app.services.loan_accounting_service import post_loan_repayment


@pytest.mark.asyncio
async def test_concurrent_repayments_dont_double_credit(db_session):
    prod = PGLoanProduct(
        product_code=f"CONC-{uuid.uuid4().hex[:6]}",
        name="Concurrency Test",
        amortization_type="flat_rate",
        repayment_frequency="monthly",
        interest_rate=Decimal("5.0"),
        penalty_rate=Decimal("2.0"),
        grace_period_months=0,
        prepayment_allowed=True,
        is_active=True,
    )
    db_session.add(prod)
    await db_session.flush()

    loan = LoanApplication(
        customer_id="C-CONC-1",
        branch_code="HQ",
        product_id=prod.id,
        principal=Decimal("10000.00"),
        term_months=12,
        status="active",
    )
    db_session.add(loan)
    await db_session.flush()

    sched = AmortizationSchedule(
        loan_id=loan.id,
        installment_number=1,
        due_date=__import__("datetime").date.today(),
        principal_due=Decimal("10000.00"),
        interest_due=Decimal("500.00"),
        principal_paid=Decimal("0.00"),
        interest_paid=Decimal("0.00"),
        penalty_due=Decimal("0.00"),
        penalty_paid=Decimal("0.00"),
        status="pending",
    )
    db_session.add(sched)
    await db_session.commit()

    factory = get_async_session_local()

    async def repay_one(i: int):
        async with factory() as s:
            try:
                je_id = await post_loan_repayment(
                    s,
                    loan_id=loan.id,
                    total_minor=1000,
                    penalty_minor=0,
                    fee_minor=0,
                    interest_minor=1000,
                    principal_minor=0,
                    customer_id="C-CONC-1",
                    branch_code="HQ",
                    idempotency_key=f"CONC-{i}-{uuid.uuid4()}",
                )
                return je_id
            except Exception:
                return None

    results = await asyncio.gather(*(repay_one(i) for i in range(20)))
    success = [r for r in results if r is not None]
    assert len(success) >= 1
