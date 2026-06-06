"""
NPL (Non-Performing Loan) service.

Marks loans as NPL when their oldest unpaid installment is 90+ DPD.
Stops interest accrual on NPL (non-accrual status).
Posts provision entries (Dr 5210 / Cr 1410) for newly-classified NPLs.

Per the GAAP-aligned rule:
  - 30+ DPD = Stage 2 (SICR, lifetime ECL)
  - 90+ DPD = Stage 3 / NPL (non-accrual)
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
)
from .loan_accounting_service import post_provision


NPL_DPD_THRESHOLD = 90
SICR_DPD_THRESHOLD = 30


async def assess_npl_status(
    db: AsyncSession,
    *,
    as_of: Optional[date] = None,
    provision_rate_pct: Optional[Decimal] = None,
    branch_code: Optional[str] = None,
) -> dict:
    """
    For every loan with an overdue installment, recompute DPD from the
    oldest unpaid installment, and:
      - DPD >= 90  -> set is_npl=True, ecl_stage='S3', non_accrual_since
      - 30 <= DPD < 90 -> ecl_stage='S2'
      - DPD < 30   -> ecl_stage='S1'
    Post a provision JE for newly-NPL'd loans.
    """
    if as_of is None:
        as_of = date.today()

    result = await db.execute(
        select(
            AmortizationSchedule.loan_id,
            func.min(AmortizationSchedule.due_date).label("oldest_due"),
            func.coalesce(
                func.sum(
                    (AmortizationSchedule.principal_due - AmortizationSchedule.principal_paid)
                    + (AmortizationSchedule.interest_due - AmortizationSchedule.interest_paid)
                ),
                0,
            ).label("outstanding"),
        )
        .where(AmortizationSchedule.status.in_(["pending", "partial", "overdue"]))
        .group_by(AmortizationSchedule.loan_id)
    )
    aging = {r.loan_id: (r.oldest_due, r.outstanding) for r in result.all()}

    newly_npl = 0
    newly_s2 = 0
    npl_count = 0
    s2_count = 0

    for loan_id, (oldest_due, outstanding) in aging.items():
        dpd = max((as_of - oldest_due).days, 0) if oldest_due else 0
        loan_q = await db.execute(
            select(LoanApplication).filter(LoanApplication.id == loan_id)
        )
        loan = loan_q.scalar_one_or_none()
        if loan is None:
            continue
        prev_npl = bool(loan.is_npl)
        prev_stage = loan.ecl_stage or "S1"

        if dpd >= NPL_DPD_THRESHOLD:
            loan.is_npl = True
            loan.ecl_stage = "S3"
            if not prev_npl:
                loan.non_accrual_since = datetime.utcnow()
                newly_npl += 1
                rate = provision_rate_pct or Decimal(20)
                amount_minor = int((Decimal(outstanding) * rate / Decimal(100) * 100).to_integral_value())
                if amount_minor > 0:
                    await post_provision(
                        db,
                        loan_id=loan_id,
                        amount_minor=amount_minor,
                        branch_code=loan.branch_code,
                        idempotency_key=f"NPL-{loan_id}-{as_of.isoformat()}",
                    )
            npl_count += 1
        elif dpd >= SICR_DPD_THRESHOLD:
            loan.ecl_stage = "S2"
            if prev_stage != "S2":
                newly_s2 += 1
            s2_count += 1
        else:
            loan.ecl_stage = "S1"
            if loan.is_npl:
                loan.is_npl = False
                loan.non_accrual_since = None

    await db.commit()
    return {
        "as_of": as_of.isoformat(),
        "npl_count": npl_count,
        "s2_count": s2_count,
        "newly_npl": newly_npl,
        "newly_s2": newly_s2,
    }


def should_accrue_interest(loan: LoanApplication) -> bool:
    """Return False when the loan is on non-accrual status."""
    return not bool(getattr(loan, "is_npl", False))
