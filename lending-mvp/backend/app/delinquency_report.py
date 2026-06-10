"""
Delinquency Report — PAR, NPL, Aging Buckets, ECL staging.
BSP Circular 941 compliant aging with 6 buckets (Current, 1-30, 31-60, 61-90, 91-180, 180+).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

import strawberry
from sqlalchemy import and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types import Info

from .auth.rbac import get_sql_branch_filter
from .database import get_async_session_local
from .database.pg_core_models import Customer
from .database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    LoanTransaction,
    PGLoanProduct,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_aging_bucket(dpd: int) -> DelinquencyAgingBucket:
    if dpd <= 0:
        return DelinquencyAgingBucket.CURRENT
    elif dpd <= 30:
        return DelinquencyAgingBucket.DPD_1_30
    elif dpd <= 60:
        return DelinquencyAgingBucket.DPD_31_60
    elif dpd <= 90:
        return DelinquencyAgingBucket.DPD_61_90
    elif dpd <= 180:
        return DelinquencyAgingBucket.DPD_91_180
    else:
        return DelinquencyAgingBucket.DPD_180_PLUS


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator and denominator > 0:
        return (numerator / denominator) * Decimal("100")
    return Decimal("0.00")


# ── Enums ────────────────────────────────────────────────────────────────


@strawberry.enum
class DelinquencyAgingBucket(Enum):
    CURRENT = "current"
    DPD_1_30 = "1_30"
    DPD_31_60 = "31_60"
    DPD_61_90 = "61_90"
    DPD_91_180 = "91_180"
    DPD_180_PLUS = "180_plus"


# ── Strawberry Types ────────────────────────────────────────────────────


@strawberry.type
class DelinquencySummary:
    totalPortfolioOutstanding: Decimal
    totalDelinquentAmount: Decimal
    totalDelinquentLoans: int
    par30: Decimal
    par60: Decimal
    par90: Decimal
    nplRatio: Decimal
    delinquentRate: Decimal


@strawberry.type
class DelinquencyAgingBucketSummary:
    bucket: DelinquencyAgingBucket
    loanCount: int
    outstandingPrincipal: Decimal
    portfolioPercent: Decimal
    principalArrears: Decimal
    interestArrears: Decimal
    penaltyArrears: Decimal


@strawberry.type
class DelinquentLoanNode:
    loanId: str
    customerId: str
    customerName: str
    branchCode: Optional[str] = None
    productName: str
    originalPrincipal: Decimal
    outstandingPrincipal: Decimal
    totalArrears: Decimal
    principalArrears: Decimal
    interestArrears: Decimal
    penaltyArrears: Decimal
    dpd: int
    agingBucket: DelinquencyAgingBucket
    oldestDueDate: Optional[date] = None
    installmentsPastDue: int
    totalInstallments: int
    lastPaymentDate: Optional[datetime] = None
    lastPaymentAmount: Optional[Decimal] = None
    collectionsOfficer: Optional[str] = None
    assignedCollectionsBranch: Optional[str] = None
    eclStage: str
    isNpl: bool
    isRestructured: bool
    status: str
    monthsPaid: int


@strawberry.type
class DelinquentLoanConnection:
    nodes: List[DelinquentLoanNode]
    totalCount: int
    totalOutstandingPrincipal: Decimal
    totalArrears: Decimal


@strawberry.type
class DelinquencyReport:
    asOf: date
    generatedAt: datetime
    branchCode: Optional[str] = None
    summary: DelinquencySummary
    agingSummary: List[DelinquencyAgingBucketSummary]
    loanDetails: DelinquentLoanConnection


# ── Resolver ────────────────────────────────────────────────────────────


async def resolve_delinquency_report(
    info: Info,
    asOf: Optional[date] = None,
    branchCode: Optional[str] = None,
) -> DelinquencyReport:
    effective_date = asOf or date.today()
    generated_at = datetime.now()

    user = info.context.get("current_user")
    if not user:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    effective_branch = branchCode or (
        get_sql_branch_filter(user) if user else None
    )

    session_factory = get_async_session_local()
    async with session_factory() as session:
        # 1. Fetch loans with product & customer info ────────────────────
        active_statuses = ("active", "defaulted", "non_accrual")

        loans_stmt = (
            select(
                LoanApplication,
                PGLoanProduct.name.label("product_name"),
                Customer.display_name,
            )
            .outerjoin(
                PGLoanProduct,
                LoanApplication.product_id == PGLoanProduct.id,
            )
            .outerjoin(
                Customer,
                cast(LoanApplication.customer_id, Customer.id.type)
                == Customer.id,
            )
            .where(LoanApplication.status.in_(active_statuses))
        )
        if effective_branch:
            loans_stmt = loans_stmt.where(
                LoanApplication.branch_code == effective_branch
            )

        loan_rows = (await session.execute(loans_stmt)).all()

        if not loan_rows:
            empty_summary = DelinquencySummary(
                totalPortfolioOutstanding=Decimal("0.00"),
                totalDelinquentAmount=Decimal("0.00"),
                totalDelinquentLoans=0,
                par30=Decimal("0.00"),
                par60=Decimal("0.00"),
                par90=Decimal("0.00"),
                nplRatio=Decimal("0.00"),
                delinquentRate=Decimal("0.00"),
            )
            return DelinquencyReport(
                asOf=effective_date,
                generatedAt=generated_at,
                branchCode=effective_branch,
                summary=empty_summary,
                agingSummary=[],
                loanDetails=DelinquentLoanConnection(
                    nodes=[],
                    totalCount=0,
                    totalOutstandingPrincipal=Decimal("0.00"),
                    totalArrears=Decimal("0.00"),
                ),
            )

        loan_ids: List[int] = []
        loan_map: Dict[int, dict] = {}
        for r in loan_rows:
            loan_app: LoanApplication = r.LoanApplication
            pid = loan_app.id
            loan_ids.append(pid)
            loan_map[pid] = {
                "loan": loan_app,
                "product_name": r.product_name or "Unknown",
                "customer_name": r.display_name
                or f"Customer {loan_app.customer_id}",
            }

        # 2. Fetch amortization schedules ───────────────────────────────
        sched_rows = (
            (
                await session.execute(
                    select(AmortizationSchedule)
                    .where(AmortizationSchedule.loan_id.in_(loan_ids))
                    .order_by(
                        AmortizationSchedule.loan_id,
                        AmortizationSchedule.installment_number,
                    )
                )
            )
            .scalars()
            .all()
        )

        sched_groups: Dict[int, List[AmortizationSchedule]] = {}
        for s in sched_rows:
            sched_groups.setdefault(s.loan_id, []).append(s)

        # 3. Fetch last repayment per loan ──────────────────────────────
        max_ts_subq = (
            select(
                LoanTransaction.loan_id,
                func.max(LoanTransaction.timestamp).label("max_ts"),
            )
            .where(LoanTransaction.type == "repayment")
            .group_by(LoanTransaction.loan_id)
            .subquery()
        )

        last_pay_stmt = (
            select(
                LoanTransaction.loan_id,
                LoanTransaction.amount,
                LoanTransaction.timestamp,
            )
            .join(
                max_ts_subq,
                and_(
                    LoanTransaction.loan_id == max_ts_subq.c.loan_id,
                    LoanTransaction.timestamp == max_ts_subq.c.max_ts,
                ),
            )
        )
        last_pay_rows = (await session.execute(last_pay_stmt)).all()
        last_pay_map: Dict[int, dict] = {}
        for r in last_pay_rows:
            last_pay_map[r.loan_id] = {
                "amount": Decimal(str(r.amount)) if r.amount else None,
                "timestamp": r.timestamp,
            }

    # 4. Process each loan in Python ────────────────────────────────────
    nodes: List[DelinquentLoanNode] = []
    total_portfolio = Decimal("0.00")
    total_delinquent_amount = Decimal("0.00")
    delinquent_loan_count = 0
    total_arrears_all = Decimal("0.00")

    # Per-bucket accumulators
    bucket_keys = list(DelinquencyAgingBucket)
    bucket_data: Dict[DelinquencyAgingBucket, dict] = {
        b: {
            "count": 0,
            "outstanding": Decimal("0.00"),
            "principal_arrears": Decimal("0.00"),
            "interest_arrears": Decimal("0.00"),
            "penalty_arrears": Decimal("0.00"),
        }
        for b in bucket_keys
    }

    for lid in loan_ids:
        info_dict = loan_map[lid]
        loan = info_dict["loan"]
        schedules = sched_groups.get(lid, [])

        outstanding = loan.outstanding_balance or loan.approved_principal or loan.principal or Decimal("0.00")
        total_portfolio += outstanding

        original_principal = loan.approved_principal or loan.principal or Decimal("0.00")

        # Identify past-due unpaid installments
        past_due = [
            s
            for s in schedules
            if s.status in ("pending", "partial", "overdue")
            and s.due_date <= effective_date
        ]

        # DPD calculation — oldest unpaid past-due installment
        oldest_unpaid = min(past_due, key=lambda s: s.due_date) if past_due else None
        dpd = max(0, (effective_date - oldest_unpaid.due_date).days) if oldest_unpaid else 0

        # Arrears
        principal_arrears = sum(
            Decimal(str((s.principal_due or 0) - (s.principal_paid or 0)))
            for s in past_due
        )
        interest_arrears = sum(
            Decimal(str((s.interest_due or 0) - (s.interest_paid or 0)))
            for s in past_due
        )
        penalty_arrears = sum(
            Decimal(str((s.penalty_due or 0) - (s.penalty_paid or 0)))
            for s in past_due
        )
        total_arrears = principal_arrears + interest_arrears + penalty_arrears
        total_arrears_all += total_arrears

        # Installment counts
        installments_past_due = len(past_due)
        total_installments = len(schedules)

        # Last payment
        last_pay = last_pay_map.get(lid)
        last_pay_date = last_pay["timestamp"] if last_pay else None
        last_pay_amount = last_pay["amount"] if last_pay else None

        # Bucket
        bucket = _get_aging_bucket(dpd)

        # Summary accumulators
        if dpd > 0:
            total_delinquent_amount += outstanding
            delinquent_loan_count += 1

        # Bucket accumulators
        bd = bucket_data[bucket]
        bd["count"] += 1
        bd["outstanding"] += outstanding
        bd["principal_arrears"] += principal_arrears
        bd["interest_arrears"] += interest_arrears
        bd["penalty_arrears"] += penalty_arrears

        # ECL staging
        ecl_stage = loan.ecl_stage or "S1"

        nodes.append(
            DelinquentLoanNode(
                loanId=str(loan.id),
                customerId=str(loan.customer_id),
                customerName=info_dict["customer_name"],
                branchCode=loan.branch_code,
                productName=info_dict["product_name"],
                originalPrincipal=original_principal,
                outstandingPrincipal=outstanding,
                totalArrears=total_arrears,
                principalArrears=principal_arrears,
                interestArrears=interest_arrears,
                penaltyArrears=penalty_arrears,
                dpd=dpd,
                agingBucket=bucket,
                oldestDueDate=oldest_unpaid.due_date if oldest_unpaid else None,
                installmentsPastDue=installments_past_due,
                totalInstallments=total_installments,
                lastPaymentDate=last_pay_date,
                lastPaymentAmount=last_pay_amount,
                collectionsOfficer=loan.collections_officer,
                assignedCollectionsBranch=loan.assigned_collections_branch,
                eclStage=ecl_stage,
                isNpl=loan.is_npl or (dpd >= 90),
                isRestructured=False,
                status=loan.status,
                monthsPaid=loan.months_paid or 0,
            )
        )

    # 5. Build summary ──────────────────────────────────────────────────
    total_loans = len(loan_ids)

    par30_num = sum(
        bd["outstanding"]
        for bkt, bd in bucket_data.items()
        if bkt
        in (DelinquencyAgingBucket.DPD_31_60, DelinquencyAgingBucket.DPD_61_90, DelinquencyAgingBucket.DPD_91_180, DelinquencyAgingBucket.DPD_180_PLUS)
    )
    par60_num = sum(
        bd["outstanding"]
        for bkt, bd in bucket_data.items()
        if bkt
        in (DelinquencyAgingBucket.DPD_61_90, DelinquencyAgingBucket.DPD_91_180, DelinquencyAgingBucket.DPD_180_PLUS)
    )
    par90_num = sum(
        bd["outstanding"]
        for bkt, bd in bucket_data.items()
        if bkt in (DelinquencyAgingBucket.DPD_91_180, DelinquencyAgingBucket.DPD_180_PLUS)
    )

    summary = DelinquencySummary(
        totalPortfolioOutstanding=total_portfolio,
        totalDelinquentAmount=total_delinquent_amount,
        totalDelinquentLoans=delinquent_loan_count,
        par30=_pct(par30_num, total_portfolio),
        par60=_pct(par60_num, total_portfolio),
        par90=_pct(par90_num, total_portfolio),
        nplRatio=_pct(par90_num, total_portfolio),
        delinquentRate=_pct(
            Decimal(str(delinquent_loan_count)),
            Decimal(str(total_loans)) if total_loans else Decimal("1"),
        ),
    )

    aging_summary: List[DelinquencyAgingBucketSummary] = []
    for bkt in bucket_keys:
        bd = bucket_data[bkt]
        aging_summary.append(
            DelinquencyAgingBucketSummary(
                bucket=bkt,
                loanCount=bd["count"],
                outstandingPrincipal=bd["outstanding"],
                portfolioPercent=_pct(bd["outstanding"], total_portfolio),
                principalArrears=bd["principal_arrears"],
                interestArrears=bd["interest_arrears"],
                penaltyArrears=bd["penalty_arrears"],
            )
        )

    loan_details = DelinquentLoanConnection(
        nodes=nodes,
        totalCount=len(nodes),
        totalOutstandingPrincipal=total_portfolio,
        totalArrears=total_arrears_all,
    )

    return DelinquencyReport(
        asOf=effective_date,
        generatedAt=generated_at,
        branchCode=effective_branch,
        summary=summary,
        agingSummary=aging_summary,
        loanDetails=loan_details,
    )
