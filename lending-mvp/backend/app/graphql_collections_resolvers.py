"""
Collections Due + Aging Report resolvers.

Single CTE-based SQL — no N+1, branch-scoped by RBAC, indexed by
(loan_id, due_date) and partial index on unpaid installments.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

import strawberry
from fastapi import HTTPException, status
from sqlalchemy import Date, case, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types import Info

from .auth.rbac import get_sql_branch_filter, require_authenticated
from .database import get_async_session_local
from .database.pg_core_models import Customer
from .database.pg_loan_models import AmortizationSchedule, LoanApplication
from .graphql_collections_schema import (
    AgingBucket,
    AgingBucketSummary,
    AgingReport,
    CollectionsDueEntry,
    CollectionsDueReport,
    CollectionsDueSummary,
    ECLStage,
)


def _aging_bucket_case(as_of_col):
    return case(
        (as_of_col <= 0, AgingBucket.CURRENT.value),
        (as_of_col <= 30, AgingBucket.DPD_1_30.value),
        (as_of_col <= 60, AgingBucket.DPD_31_60.value),
        (as_of_col <= 90, AgingBucket.DPD_61_90.value),
        (as_of_col <= 180, AgingBucket.DPD_91_180.value),
        else_=AgingBucket.DPD_180_PLUS.value,
    )


def _ecl_stage_case(dpd_col):
    return case(
        (dpd_col >= 90, ECLStage.S3.value),
        (dpd_col >= 30, ECLStage.S2.value),
        else_=ECLStage.S1.value,
    )


_COLLECTIONS_DUE_ROLES = {"admin", "branch_manager", "loan_officer", "collections_officer", "teller", "auditor"}
_AGING_REPORT_ROLES = {"admin", "branch_manager", "auditor"}


async def resolve_collections_due(
    info: Info,
    as_of: Optional[date] = None,
    branch_code: Optional[str] = None,
    collections_officer_id: Optional[str] = None,
    due_date_from: Optional[date] = None,
    due_date_to: Optional[date] = None,
    limit: int = 500,
    offset: int = 0,
) -> CollectionsDueReport:
    user = require_authenticated(info)
    if user.role not in _COLLECTIONS_DUE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for collections_due",
        )

    effective_date = as_of or date.today()
    effective_branch = branch_code or get_sql_branch_filter(user)

    # Auto-filter: collections_officer role sees only their assigned loans
    if user.role == "collections_officer" and not collections_officer_id:
        collections_officer_id = str(getattr(user, "id", ""))

    session_factory = get_async_session_local()
    async with session_factory() as session:  # type: AsyncSession
        sched_subq = (
            select(
                AmortizationSchedule.loan_id.label("loan_id"),
                AmortizationSchedule.installment_number.label("installment_number"),
                AmortizationSchedule.due_date.label("due_date"),
                AmortizationSchedule.principal_due.label("principal_due"),
                AmortizationSchedule.interest_due.label("interest_due"),
                AmortizationSchedule.penalty_due.label("penalty_due"),
                (
                    AmortizationSchedule.principal_paid
                    + AmortizationSchedule.interest_paid
                    + AmortizationSchedule.penalty_paid
                ).label("amount_paid"),
                AmortizationSchedule.status.label("installment_status"),
                LoanApplication.customer_id.label("customer_id"),
                LoanApplication.branch_code.label("branch_code"),
                LoanApplication.is_npl.label("is_npl"),
                LoanApplication.ecl_stage.label("ecl_stage"),
                LoanApplication.collections_officer.label("collections_officer"),
                LoanApplication.assigned_collections_branch.label("assigned_collections_branch"),
                Customer.display_name.label("customer_name"),
                Customer.mobile_number.label("mobile_number"),
            )
            .select_from(AmortizationSchedule)
            .join(LoanApplication, LoanApplication.id == AmortizationSchedule.loan_id)
            .outerjoin(
                Customer,
                cast(LoanApplication.customer_id, Customer.id.type) == Customer.id,
            )
            .where(AmortizationSchedule.due_date <= effective_date)
            .where(AmortizationSchedule.status.in_(["pending", "partial", "overdue"]))
            .where(LoanApplication.status.notin_(["closed", "paid", "written_off"]))
        )
        if effective_branch:
            sched_subq = sched_subq.where(LoanApplication.branch_code == effective_branch)
        if collections_officer_id:
            sched_subq = sched_subq.where(LoanApplication.collections_officer == collections_officer_id)
        sched_subq = sched_subq.subquery("sched")

        oldest_subq = (
            select(
                sched_subq.c.loan_id.label("loan_id"),
                func.min(sched_subq.c.due_date).label("oldest_due"),
            )
            .group_by(sched_subq.c.loan_id)
            .subquery("oldest")
        )

        dpd_expr = func.greatest(cast(effective_date, Date) - oldest_subq.c.oldest_due, 0)
        total_due_expr = (
            sched_subq.c.principal_due
            + sched_subq.c.interest_due
            + sched_subq.c.penalty_due
        )
        balance_due_expr = func.greatest(total_due_expr - sched_subq.c.amount_paid, 0)

        stmt = (
            select(
                sched_subq.c.loan_id,
                sched_subq.c.customer_id,
                sched_subq.c.customer_name,
                sched_subq.c.branch_code,
                sched_subq.c.installment_number,
                sched_subq.c.due_date,
                sched_subq.c.principal_due,
                sched_subq.c.interest_due,
                sched_subq.c.penalty_due,
                literal(Decimal("0.00")).label("fee_due"),
                total_due_expr.label("total_due"),
                sched_subq.c.amount_paid,
                balance_due_expr.label("balance_due"),
                dpd_expr.label("dpd"),
                _aging_bucket_case(dpd_expr).label("aging_bucket"),
                _ecl_stage_case(dpd_expr).label("ecl_stage"),
                sched_subq.c.is_npl,
                sched_subq.c.collections_officer,
                sched_subq.c.assigned_collections_branch,
                sched_subq.c.mobile_number,
            )
            .select_from(sched_subq)
            .join(oldest_subq, oldest_subq.c.loan_id == sched_subq.c.loan_id)
            .order_by(sched_subq.c.branch_code, sched_subq.c.due_date, sched_subq.c.installment_number)
            .limit(limit)
            .offset(offset)
        )

        rows = (await session.execute(stmt)).all()

        entries: List[CollectionsDueEntry] = []
        for r in rows:
            try:
                bucket = AgingBucket(r.aging_bucket)
            except ValueError:
                bucket = AgingBucket.CURRENT
            try:
                stage = ECLStage(r.ecl_stage or "S1")
            except ValueError:
                stage = ECLStage.S1
            entries.append(
                CollectionsDueEntry(
                    loan_id=strawberry.ID(str(r.loan_id)),
                    customer_id=strawberry.ID(str(r.customer_id)) if r.customer_id is not None else strawberry.ID("0"),
                    customer_name=r.customer_name or f"Customer {r.customer_id}",
                    branch_code=r.branch_code,
                    installment_no=int(r.installment_number),
                    due_date=r.due_date,
                    principal_due=Decimal(r.principal_due or 0),
                    interest_due=Decimal(r.interest_due or 0),
                    penalty_due=Decimal(r.penalty_due or 0),
                    fee_due=Decimal(r.fee_due or 0),
                    total_due=Decimal(r.total_due or 0),
                    amount_paid=Decimal(r.amount_paid or 0),
                    balance_due=Decimal(r.balance_due or 0),
                    dpd=int(r.dpd or 0),
                    aging_bucket=bucket,
                    ecl_stage=stage,
                    is_npl=bool(r.is_npl),
                    collections_officer=r.collections_officer,
                    assigned_collections_branch=r.assigned_collections_branch,
                    mobile_number=r.mobile_number,
                )
            )

        total_principal_due = sum((e.principal_due for e in entries), Decimal(0))
        total_interest_due = sum((e.interest_due for e in entries), Decimal(0))
        total_penalty_due = sum((e.penalty_due for e in entries), Decimal(0))
        total_fee_due = sum((e.fee_due for e in entries), Decimal(0))
        total_balance_due = sum((e.balance_due for e in entries), Decimal(0))

        return CollectionsDueReport(
            as_of=effective_date,
            branch_code=effective_branch,
            total_entries=len(entries),
            total_principal_due=total_principal_due,
            total_interest_due=total_interest_due,
            total_penalty_due=total_penalty_due,
            total_fee_due=total_fee_due,
            total_balance_due=total_balance_due,
            entries=entries,
        )


async def resolve_collections_due_summary(
    info: Info,
    as_of: Optional[date] = None,
    branch_code: Optional[str] = None,
) -> CollectionsDueSummary:
    report = await resolve_collections_due(info, as_of, branch_code, limit=100000, offset=0)
    seen = set()
    for e in report.entries:
        seen.add(str(e.loan_id))
    return CollectionsDueSummary(
        as_of=report.as_of,
        branch_code=report.branch_code,
        total_overdue_loans=len(seen),
        total_overdue_amount=report.total_balance_due,
        total_principal_overdue=report.total_principal_due,
        total_interest_overdue=report.total_interest_due,
        total_penalty_overdue=report.total_penalty_due,
    )


async def resolve_aging_report(
    info: Info,
    as_of: Optional[date] = None,
    branch_code: Optional[str] = None,
) -> AgingReport:
    user = require_authenticated(info)
    if user.role not in _AGING_REPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for aging_report",
        )

    effective_date = as_of or date.today()
    effective_branch = branch_code or get_sql_branch_filter(user)

    session_factory = get_async_session_local()
    async with session_factory() as session:  # type: AsyncSession
        sched_subq = (
            select(
                AmortizationSchedule.loan_id.label("loan_id"),
                AmortizationSchedule.due_date.label("due_date"),
                AmortizationSchedule.principal_due.label("principal_due"),
                AmortizationSchedule.principal_paid.label("principal_paid"),
                LoanApplication.branch_code.label("branch_code"),
            )
            .select_from(AmortizationSchedule)
            .join(LoanApplication, LoanApplication.id == AmortizationSchedule.loan_id)
            .where(AmortizationSchedule.due_date <= effective_date)
            .where(AmortizationSchedule.status.notin_(["paid", "waived"]))
            .where(LoanApplication.status.notin_(["closed", "paid", "written_off"]))
        )
        if effective_branch:
            sched_subq = sched_subq.where(LoanApplication.branch_code == effective_branch)
        sched_subq = sched_subq.subquery("sched")

        oldest_subq = (
            select(
                sched_subq.c.loan_id.label("loan_id"),
                func.min(sched_subq.c.due_date).label("oldest_due"),
                func.coalesce(
                    func.sum(sched_subq.c.principal_due - sched_subq.c.principal_paid),
                    0,
                ).label("outstanding_principal"),
            )
            .group_by(sched_subq.c.loan_id)
            .subquery("oldest")
        )

        dpd_expr = func.greatest(cast(effective_date, Date) - oldest_subq.c.oldest_due, 0)
        bucket_expr = _aging_bucket_case(dpd_expr)

        bucket_q = (
            select(
                bucket_expr.label("bucket"),
                func.count().label("loan_count"),
                func.coalesce(func.sum(oldest_subq.c.outstanding_principal), 0).label(
                    "outstanding_principal"
                ),
            )
            .group_by(bucket_expr)
        )

        bucket_rows = (await session.execute(bucket_q)).all()
        total_outstanding = sum(
            (Decimal(r.outstanding_principal or 0) for r in bucket_rows), Decimal(0)
        )

        buckets: List[AgingBucketSummary] = []
        for r in bucket_rows:
            try:
                bucket = AgingBucket(r.bucket)
            except ValueError:
                bucket = AgingBucket.CURRENT
            is_npl = bucket in (AgingBucket.DPD_91_180, AgingBucket.DPD_180_PLUS)
            outstanding = Decimal(r.outstanding_principal or 0)
            pct = (
                float(outstanding) / float(total_outstanding) * 100.0
                if total_outstanding > 0
                else 0.0
            )
            buckets.append(
                AgingBucketSummary(
                    bucket=bucket,
                    loan_count=int(r.loan_count or 0),
                    outstanding_principal=outstanding,
                    pct_of_portfolio=round(pct, 2),
                    is_npl=is_npl,
                )
            )

        par30_amount = sum(
            (
                b.outstanding_principal
                for b in buckets
                if b.bucket in (
                    AgingBucket.DPD_31_60,
                    AgingBucket.DPD_61_90,
                    AgingBucket.DPD_91_180,
                    AgingBucket.DPD_180_PLUS,
                )
            ),
            Decimal(0),
        )
        npl_amount = sum(
            (b.outstanding_principal for b in buckets if b.is_npl), Decimal(0)
        )
        denominator = total_outstanding if total_outstanding > 0 else Decimal("0.01")
        npl_ratio = round(float(npl_amount) / float(denominator), 4)
        par30_ratio = round(float(par30_amount) / float(denominator), 4)

        return AgingReport(
            as_of=effective_date,
            branch_code=effective_branch,
            total_outstanding=total_outstanding,
            npl_ratio=npl_ratio,
            par30_ratio=par30_ratio,
            buckets=buckets,
        )
