"""
Loan accounting service.

Post the GAAP-compliant double-entry journal entries for:
- Loan disbursement
- Loan repayment (waterfall: penalty -> fee -> interest -> principal)
- Loan write-off
- Recovery
- Interest accrual
- Penalty assessment
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounting import generate_reference_number
from ..database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    LoanTransaction,
)
from .accounting_service import post_transaction


ACCT_LOANS_RECEIVABLE_CURRENT = "1200"
ACCT_LOANS_RECEIVABLE_NON_CURRENT = "1205"
ACCT_INTEREST_RECEIVABLE = "1210"
ACCT_PENALTY_RECEIVABLE = "1220"
ACCT_CASH_BANK = "1010"
ACCT_FEE_INCOME_ORIG = "4200"
ACCT_PENALTY_INCOME = "4300"
ACCT_INTEREST_INCOME_LOANS = "4100"
ACCT_INTEREST_INCOME_ACCRUED = "4110"
ACCT_PREPAY_PENALTY_INCOME = "4400"
ACCT_OVERPAYMENTS = "2100"
ACCT_SAVINGS_DEPOSITS = "2030"
ACCT_ALLOWANCE_FOR_LOSSES = "1410"
ACCT_LOAN_LOSS_EXPENSE = "5200"
ACCT_PROVISION_FOR_CREDIT_LOSSES = "5210"
ACCT_RECOVERY_INCOME = "4600"


def _to_minor(value) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int((value * 100).to_integral_value())
    raise TypeError(f"unsupported money type: {type(value).__name__}")


async def post_loan_disbursement(
    db: AsyncSession,
    *,
    loan_id: int,
    principal_minor: int,
    net_disbursement_minor: int,
    origination_fee_minor: int = 0,
    customer_id: Optional[str] = None,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    """
    Disbursement posting (Dr 1200 Loans Receivable, Cr 1010 Cash; if orig fee
    exists, also Cr 4200 Fee Income Origination for the net difference).
    """
    if principal_minor <= 0:
        raise ValueError("principal must be positive")
    if net_disbursement_minor < 0:
        raise ValueError("net_disbursement must be >= 0")

    legs = [
        {
            "account_code": ACCT_LOANS_RECEIVABLE_CURRENT,
            "debit_minor": principal_minor,
            "credit_minor": 0,
            "description": f"Loan disbursement #{loan_id}",
        },
        {
            "account_code": ACCT_CASH_BANK,
            "debit_minor": 0,
            "credit_minor": net_disbursement_minor,
            "description": f"Cash out for loan #{loan_id}",
        },
    ]
    if origination_fee_minor > 0:
        legs.append({
            "account_code": ACCT_FEE_INCOME_ORIG,
            "debit_minor": 0,
            "credit_minor": origination_fee_minor,
            "description": f"Origination fee for loan #{loan_id}",
        })

    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=description or f"Loan disbursement #{loan_id}",
        reference_no=generate_reference_number("DISB"),
        created_by=created_by,
        value_date=date.today(),
        branch_code=branch_code,
        loan_id=loan_id,
        customer_id=customer_id,
    )


async def post_loan_repayment(
    db: AsyncSession,
    *,
    loan_id: int,
    total_minor: int,
    penalty_minor: int,
    fee_minor: int,
    interest_minor: int,
    principal_minor: int,
    overpayment_minor: int = 0,
    customer_id: Optional[str] = None,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
    value_date: Optional[date] = None,
) -> int:
    """
    Repayment waterfall posting. The allocation is computed upstream and
    passed in; this function only posts the balanced journal.

    Allocations (in priority order):
        penalty -> fee -> interest -> principal -> overpayment
    """
    if total_minor <= 0:
        raise ValueError("total must be positive")
    if any(x < 0 for x in (penalty_minor, fee_minor, interest_minor, principal_minor, overpayment_minor)):
        raise ValueError("allocations must be non-negative")
    if (penalty_minor + fee_minor + interest_minor + principal_minor + overpayment_minor) != total_minor:
        raise ValueError("allocations must sum to total")

    legs = [
        {
            "account_code": ACCT_CASH_BANK,
            "debit_minor": total_minor,
            "credit_minor": 0,
            "description": f"Cash in for loan #{loan_id}",
        },
    ]
    if penalty_minor > 0:
        legs.append({
            "account_code": ACCT_PENALTY_INCOME,
            "debit_minor": 0,
            "credit_minor": penalty_minor,
            "description": f"Penalty income #{loan_id}",
        })
    if fee_minor > 0:
        legs.append({
            "account_code": ACCT_FEE_INCOME_ORIG,
            "debit_minor": 0,
            "credit_minor": fee_minor,
            "description": f"Fee income #{loan_id}",
        })
    if interest_minor > 0:
        legs.append({
            "account_code": ACCT_INTEREST_INCOME_LOANS,
            "debit_minor": 0,
            "credit_minor": interest_minor,
            "description": f"Interest income #{loan_id}",
        })
    if principal_minor > 0:
        legs.append({
            "account_code": ACCT_LOANS_RECEIVABLE_CURRENT,
            "debit_minor": 0,
            "credit_minor": principal_minor,
            "description": f"Principal repaid #{loan_id}",
        })
    if overpayment_minor > 0:
        legs.append({
            "account_code": ACCT_OVERPAYMENTS,
            "debit_minor": 0,
            "credit_minor": overpayment_minor,
            "description": f"Overpayment held #{loan_id}",
        })

    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=f"Loan repayment #{loan_id}",
        reference_no=generate_reference_number("REPAY"),
        created_by=created_by,
        value_date=value_date or date.today(),
        branch_code=branch_code,
        loan_id=loan_id,
        customer_id=customer_id,
    )


async def post_penalty_assessment(
    db: AsyncSession,
    *,
    loan_id: int,
    amount_minor: int,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
) -> int:
    if amount_minor <= 0:
        raise ValueError("amount must be positive")
    legs = [
        {
            "account_code": ACCT_PENALTY_RECEIVABLE,
            "debit_minor": amount_minor,
            "credit_minor": 0,
            "description": f"Penalty assessed #{loan_id}",
        },
        {
            "account_code": ACCT_PENALTY_INCOME,
            "debit_minor": 0,
            "credit_minor": amount_minor,
            "description": f"Penalty income accrual #{loan_id}",
        },
    ]
    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=f"Penalty assessment #{loan_id}",
        reference_no=generate_reference_number("PEN"),
        created_by=created_by,
        branch_code=branch_code,
        loan_id=loan_id,
    )


async def post_interest_accrual(
    db: AsyncSession,
    *,
    loan_id: int,
    amount_minor: int,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
) -> int:
    if amount_minor <= 0:
        raise ValueError("amount must be positive")
    legs = [
        {
            "account_code": ACCT_INTEREST_RECEIVABLE,
            "debit_minor": amount_minor,
            "credit_minor": 0,
            "description": f"Interest accrued #{loan_id}",
        },
        {
            "account_code": ACCT_INTEREST_INCOME_ACCRUED,
            "debit_minor": 0,
            "credit_minor": amount_minor,
            "description": f"Interest income accrual #{loan_id}",
        },
    ]
    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=f"Interest accrual #{loan_id}",
        reference_no=generate_reference_number("ACCR"),
        created_by=created_by,
        branch_code=branch_code,
        loan_id=loan_id,
    )


async def post_writeoff(
    db: AsyncSession,
    *,
    loan_id: int,
    principal_minor: int,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
) -> int:
    """
    Write-off the uncollectible principal against the ALLL contra-asset.
    Two-entry flow is upstream — caller posts the provision first if needed.
    """
    if principal_minor <= 0:
        raise ValueError("principal must be positive")
    legs = [
        {
            "account_code": ACCT_ALLOWANCE_FOR_LOSSES,
            "debit_minor": principal_minor,
            "credit_minor": 0,
            "description": f"Write-off from ALLL #{loan_id}",
        },
        {
            "account_code": ACCT_LOANS_RECEIVABLE_CURRENT,
            "debit_minor": 0,
            "credit_minor": principal_minor,
            "description": f"Write-off loan principal #{loan_id}",
        },
    ]
    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=f"Loan write-off #{loan_id}",
        reference_no=generate_reference_number("WO"),
        created_by=created_by,
        branch_code=branch_code,
        loan_id=loan_id,
    )


async def post_provision(
    db: AsyncSession,
    *,
    loan_id: Optional[int],
    amount_minor: int,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    created_by: Optional[str] = None,
) -> int:
    """Dr 5210 Provision for Credit Losses / Cr 1410 ALLL."""
    if amount_minor <= 0:
        raise ValueError("amount must be positive")
    legs = [
        {
            "account_code": ACCT_PROVISION_FOR_CREDIT_LOSSES,
            "debit_minor": amount_minor,
            "credit_minor": 0,
            "description": f"Provision #{loan_id or 'global'}",
        },
        {
            "account_code": ACCT_ALLOWANCE_FOR_LOSSES,
            "debit_minor": 0,
            "credit_minor": amount_minor,
            "description": f"ALLL increase #{loan_id or 'global'}",
        },
    ]
    return await post_transaction(
        db,
        legs,
        idempotency_key=idempotency_key,
        description=f"Loan loss provision #{loan_id or 'global'}",
        reference_no=generate_reference_number("PROV"),
        created_by=created_by,
        branch_code=branch_code,
        loan_id=loan_id,
    )
