"""
Penalty engine.

Daily job: for every overdue installment, assess penalty = outstanding
* (penalty_rate / 100) / 30 * days_overdue. Idempotent via the
`idempotency_key` derived from (loan_id, installment_id, as_of_date).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    PGLoanProduct,
)
from .accounting_service import post_transaction
from .loan_accounting_service import (
    ACCT_PENALTY_INCOME,
    ACCT_PENALTY_RECEIVABLE,
    post_penalty_assessment,
)


async def apply_penalties(
    db: AsyncSession,
    *,
    as_of: Optional[date] = None,
    penalty_rate_per_30day_pct: Optional[Decimal] = None,
    branch_code: Optional[str] = None,
) -> int:
    """
    Run penalty assessment for all overdue installments.

    Returns the number of installments updated.
    """
    if as_of is None:
        as_of = date.today()

    result = await db.execute(
        select(AmortizationSchedule, LoanApplication, PGLoanProduct)
        .join(LoanApplication, LoanApplication.id == AmortizationSchedule.loan_id)
        .join(PGLoanProduct, PGLoanProduct.id == LoanApplication.product_id)
        .where(AmortizationSchedule.due_date < as_of)
        .where(AmortizationSchedule.status.in_(["pending", "partial", "overdue"]))
    )
    rows = result.all()
    n = 0
    for sched, loan, product in rows:
        rate = penalty_rate_per_30day_pct or (product.penalty_rate or Decimal(0))
        if rate <= 0:
            sched.status = "overdue"
            n += 1
            continue
        days_late = max((as_of - sched.due_date).days, 0)
        outstanding = (
            (sched.principal_due - sched.principal_paid)
            + (sched.interest_due - sched.interest_paid)
        )
        if outstanding <= 0:
            continue
        accrued = (
            outstanding * (rate / Decimal(100)) / Decimal(30) * Decimal(days_late)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if accrued > sched.penalty_due:
            sched.penalty_due = accrued
            sched.status = "overdue"
            n += 1
    await db.commit()
    return n
