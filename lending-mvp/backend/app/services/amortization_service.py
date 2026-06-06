"""
Amortization schedule service.

Builds and persists a per-loan installment schedule on disbursement.
Supports flat-rate, declining-balance, and interest-only amortization.

All amounts in integer minor units internally; the API takes/returns
Decimal for backward compatibility.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    PGLoanProduct,
)


def _to_minor(value: Decimal) -> int:
    return int((value * Decimal(100)).to_integral_value())


def _from_minor(value: int) -> Decimal:
    return (Decimal(value) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def build_flat_schedule(
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    start_date: date,
) -> List[dict]:
    monthly_rate = (annual_rate_pct / Decimal(100)) / Decimal(12)
    total_interest = principal * monthly_rate * Decimal(term_months)
    total = principal + total_interest
    installment = (total / Decimal(term_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rows: List[dict] = []
    for i in range(term_months):
        principal_leg = (principal / Decimal(term_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        interest_leg = installment - principal_leg
        rows.append({
            "installment_number": i + 1,
            "due_date": _add_months(start_date, i + 1),
            "principal_due": _to_minor(principal_leg),
            "interest_due": _to_minor(interest_leg),
        })
    return rows


def build_declining_schedule(
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    start_date: date,
) -> List[dict]:
    monthly_rate = (annual_rate_pct / Decimal(100)) / Decimal(12)
    if monthly_rate == 0:
        emi = (principal / Decimal(term_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows: List[dict] = []
        for i in range(term_months):
            rows.append({
                "installment_number": i + 1,
                "due_date": _add_months(start_date, i + 1),
                "principal_due": _to_minor(emi),
                "interest_due": 0,
            })
        return rows

    factor = (Decimal(1) + monthly_rate) ** term_months
    emi = (principal * monthly_rate * factor / (factor - Decimal(1))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    balance = principal
    rows = []
    for i in range(term_months):
        interest_leg = (balance * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        principal_leg = emi - interest_leg
        if i == term_months - 1:
            principal_leg = balance
        balance -= principal_leg
        rows.append({
            "installment_number": i + 1,
            "due_date": _add_months(start_date, i + 1),
            "principal_due": _to_minor(principal_leg),
            "interest_due": _to_minor(interest_leg),
        })
    return rows


def build_interest_only_schedule(
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    start_date: date,
) -> List[dict]:
    monthly_rate = (annual_rate_pct / Decimal(100)) / Decimal(12)
    interest_leg = (principal * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rows = []
    for i in range(term_months):
        is_last = (i == term_months - 1)
        rows.append({
            "installment_number": i + 1,
            "due_date": _add_months(start_date, i + 1),
            "principal_due": _to_minor(principal) if is_last else 0,
            "interest_due": _to_minor(interest_leg),
        })
    return rows


def build_balloon_schedule(
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    start_date: date,
) -> List[dict]:
    monthly_rate = (annual_rate_pct / Decimal(100)) / Decimal(12)
    interest_leg = (principal * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rows = []
    for i in range(term_months):
        is_last = (i == term_months - 1)
        rows.append({
            "installment_number": i + 1,
            "due_date": _add_months(start_date, i + 1),
            "principal_due": _to_minor(principal) if is_last else 0,
            "interest_due": _to_minor(interest_leg),
        })
    return rows


def build_schedule(
    amortization_type: str,
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    start_date: date,
) -> List[dict]:
    if amortization_type == "flat_rate":
        return build_flat_schedule(principal, annual_rate_pct, term_months, start_date)
    if amortization_type == "declining_balance":
        return build_declining_schedule(principal, annual_rate_pct, term_months, start_date)
    if amortization_type == "interest_only":
        return build_interest_only_schedule(principal, annual_rate_pct, term_months, start_date)
    if amortization_type == "balloon_payment":
        return build_balloon_schedule(principal, annual_rate_pct, term_months, start_date)
    raise ValueError(f"Unknown amortization_type: {amortization_type}")


async def build_and_persist_schedule(
    db: AsyncSession,
    *,
    loan_id: int,
    principal: Decimal,
    annual_rate_pct: Decimal,
    term_months: int,
    amortization_type: str,
    start_date: Optional[date] = None,
) -> List[int]:
    if start_date is None:
        start_date = date.today()
    rows = build_schedule(amortization_type, principal, annual_rate_pct, term_months, start_date)
    ids: List[int] = []
    for r in rows:
        sched = AmortizationSchedule(
            loan_id=loan_id,
            installment_number=r["installment_number"],
            due_date=r["due_date"],
            principal_due=_from_minor(r["principal_due"]),
            interest_due=_from_minor(r["interest_due"]),
            penalty_due=Decimal("0.00"),
            principal_paid=Decimal("0.00"),
            interest_paid=Decimal("0.00"),
            penalty_paid=Decimal("0.00"),
            status="pending",
        )
        db.add(sched)
        await db.flush()
        ids.append(sched.id)
    return ids
