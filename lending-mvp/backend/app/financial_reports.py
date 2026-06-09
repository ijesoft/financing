"""
Financial Reports — Trial Balance, Income Statement, Balance Sheet, AR Aging, AP Aging.

All resolvers use date-filtered GL balances for period-accurate reporting.
GAAP-compliant with proper normal balance direction.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

import strawberry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types import Info

from .auth.rbac import get_sql_branch_filter
from .database import get_async_session_local
from .database.pg_accounting_models import GLAccount, JournalEntry, JournalLine
from .database.pg_core_models import Customer
from .database.pg_loan_models import AmortizationSchedule, LoanApplication


async def _get_account_balances_up_to(
    session: AsyncSession,
    as_of_date: date,
    branch_code: Optional[str] = None,
) -> Dict[str, dict]:
    entry_subq = (
        select(JournalEntry.id)
        .where(
            (JournalEntry.value_date <= as_of_date) |
            ((JournalEntry.value_date.is_(None)) & (JournalEntry.timestamp <= as_of_date))
        )
    )
    if branch_code:
        entry_subq = entry_subq.where(JournalEntry.branch_code == branch_code)
    entry_subq = entry_subq.subquery("filtered_entries")

    stmt = (
        select(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("total_credit"),
        )
        .select_from(JournalLine)
        .join(entry_subq, JournalLine.entry_id == entry_subq.c.id)
        .group_by(JournalLine.account_code)
    )
    rows = (await session.execute(stmt)).all()

    accts_result = await session.execute(
        select(GLAccount.code, GLAccount.name, GLAccount.type)
    )
    accts_map = {r.code: {"name": r.name, "type": r.type} for r in accts_result.all()}

    result = {}
    for r in rows:
        code = r.account_code
        meta = accts_map.get(code)
        if not meta:
            continue
        debit = Decimal(str(r.total_debit))
        credit = Decimal(str(r.total_credit))
        if meta["type"] in ("asset", "expense"):
            balance = debit - credit
        else:
            balance = credit - debit
        result[code] = {
            "code": code, "name": meta["name"], "type": meta["type"],
            "total_debit": debit, "total_credit": credit, "balance": balance,
        }
    return result


async def _get_period_balances(
    session: AsyncSession,
    year: int,
    month: int,
    branch_code: Optional[str] = None,
) -> Dict[str, dict]:
    period_start = date(year, month, 1)
    period_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    entry_subq = (
        select(JournalEntry.id)
        .where(JournalEntry.value_date >= period_start)
        .where(JournalEntry.value_date < period_end)
    )
    if branch_code:
        entry_subq = entry_subq.where(JournalEntry.branch_code == branch_code)
    entry_subq = entry_subq.subquery("period_entries")

    stmt = (
        select(
            JournalLine.account_code,
            func.coalesce(func.sum(JournalLine.debit), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("total_credit"),
        )
        .select_from(JournalLine)
        .join(entry_subq, JournalLine.entry_id == entry_subq.c.id)
        .group_by(JournalLine.account_code)
    )
    rows = (await session.execute(stmt)).all()

    accts_result = await session.execute(
        select(GLAccount.code, GLAccount.name, GLAccount.type)
    )
    accts_map = {r.code: {"name": r.name, "type": r.type} for r in accts_result.all()}

    result = {}
    for r in rows:
        code = r.account_code
        meta = accts_map.get(code)
        if not meta:
            continue
        debit = Decimal(str(r.total_debit))
        credit = Decimal(str(r.total_credit))
        if meta["type"] in ("asset", "expense"):
            balance = debit - credit
        else:
            balance = credit - debit
        result[code] = {
            "code": code, "name": meta["name"], "type": meta["type"],
            "total_debit": debit, "total_credit": credit, "balance": balance,
        }
    return result


@strawberry.type
class TrialBalanceRow:
    code: str
    name: str
    type: str
    totalDebit: Decimal
    totalCredit: Decimal
    balance: Decimal


@strawberry.type
class TrialBalanceReport:
    asOf: date
    rows: List[TrialBalanceRow]
    totalDebit: Decimal
    totalCredit: Decimal
    rowCount: int


@strawberry.type
class IncomeStatementRow:
    code: str
    name: str
    balance: Decimal


@strawberry.type
class IncomeStatementReport:
    year: int
    month: int
    revenueRows: List[IncomeStatementRow]
    totalRevenue: Decimal
    expenseRows: List[IncomeStatementRow]
    totalExpenses: Decimal
    netIncome: Decimal


@strawberry.type
class BalanceSheetRow:
    code: str
    name: str
    balance: Decimal


@strawberry.type
class BalanceSheetSection:
    label: str
    rows: List[BalanceSheetRow]
    total: Decimal


@strawberry.type
class BalanceSheetReport:
    asOf: date
    assets: BalanceSheetSection
    liabilities: BalanceSheetSection
    equity: BalanceSheetSection
    totalAssets: Decimal
    totalLiabilities: Decimal
    totalEquity: Decimal


@strawberry.type
class ARAgingBucket:
    label: str
    amount: Decimal


@strawberry.type
class ARAgingCustomerRow:
    customerId: str
    customerName: str
    loanId: str
    branchCode: str
    totalDue: Decimal
    buckets: List[ARAgingBucket]


@strawberry.type
class ARAgingReport:
    asOf: date
    rows: List[ARAgingCustomerRow]
    bucketTotals: List[ARAgingBucket]
    grandTotal: Decimal
    rowCount: int


@strawberry.type
class APAgingRow:
    referenceNo: str
    branchCode: str
    amount: Decimal
    dueDate: date
    agingBucket: str
    daysPastDue: int
    customerName: Optional[str] = None
    loanId: Optional[str] = None
    buckets: List[ARAgingBucket]

    @strawberry.field
    def totalBalance(self) -> Decimal:
        return self.amount


@strawberry.type
class APAgingReport:
    asOf: date
    rows: List[APAgingRow]
    bucketTotals: List[ARAgingBucket]
    grandTotal: Decimal
    rowCount: int


async def resolve_trial_balance(
    info: Info,
    asOf: Optional[date] = None,
) -> TrialBalanceReport:
    effective_date = asOf or date.today()
    user = info.context.get("current_user")
    branch_code = get_sql_branch_filter(user) if user else None

    session_factory = get_async_session_local()
    async with session_factory() as session:
        balances = await _get_account_balances_up_to(session, effective_date, branch_code)

    sorted_codes = sorted(balances.keys(), key=lambda c: int(c) if c.isdigit() else c)
    rows: List[TrialBalanceRow] = []
    total_dr = Decimal("0.00")
    total_cr = Decimal("0.00")
    for code in sorted_codes:
        b = balances[code]
        rows.append(TrialBalanceRow(
            code=b["code"], name=b["name"], type=b["type"],
            totalDebit=b["total_debit"], totalCredit=b["total_credit"], balance=b["balance"],
        ))
        total_dr += b["total_debit"]
        total_cr += b["total_credit"]

    return TrialBalanceReport(
        asOf=effective_date, rows=rows,
        totalDebit=total_dr, totalCredit=total_cr, rowCount=len(rows),
    )


async def resolve_income_statement(
    info: Info,
    year: int,
    month: int,
) -> IncomeStatementReport:
    user = info.context.get("current_user")
    branch_code = get_sql_branch_filter(user) if user else None

    session_factory = get_async_session_local()
    async with session_factory() as session:
        balances = await _get_period_balances(session, year, month, branch_code)

    revenue_rows: List[IncomeStatementRow] = []
    expense_rows: List[IncomeStatementRow] = []
    total_rev = Decimal("0.00")
    total_exp = Decimal("0.00")

    for code in sorted(balances.keys(), key=lambda c: int(c) if c.isdigit() else c):
        b = balances[code]
        if b["type"] == "income":
            revenue_rows.append(IncomeStatementRow(code=b["code"], name=b["name"], balance=b["balance"]))
            total_rev += b["balance"]
        elif b["type"] == "expense":
            expense_rows.append(IncomeStatementRow(code=b["code"], name=b["name"], balance=b["balance"]))
            total_exp += b["balance"]

    return IncomeStatementReport(
        year=year, month=month,
        revenueRows=revenue_rows, totalRevenue=total_rev,
        expenseRows=expense_rows, totalExpenses=total_exp,
        netIncome=total_rev - total_exp,
    )


async def resolve_balance_sheet(
    info: Info,
    asOf: Optional[date] = None,
) -> BalanceSheetReport:
    effective_date = asOf or date.today()
    user = info.context.get("current_user")
    branch_code = get_sql_branch_filter(user) if user else None

    session_factory = get_async_session_local()
    async with session_factory() as session:
        balances = await _get_account_balances_up_to(session, effective_date, branch_code)

    asset_rows: List[BalanceSheetRow] = []
    liability_rows: List[BalanceSheetRow] = []
    equity_rows: List[BalanceSheetRow] = []
    total_assets = Decimal("0.00")
    total_liabilities = Decimal("0.00")
    total_equity = Decimal("0.00")

    accumulated_income = Decimal("0.00")
    accumulated_expense = Decimal("0.00")
    for code in sorted(balances.keys(), key=lambda c: int(c) if c.isdigit() else c):
        b = balances[code]
        row = BalanceSheetRow(code=b["code"], name=b["name"], balance=b["balance"])
        if b["type"] == "asset":
            asset_rows.append(row)
            total_assets += b["balance"]
        elif b["type"] == "liability":
            liability_rows.append(row)
            total_liabilities += b["balance"]
        elif b["type"] == "equity":
            equity_rows.append(row)
            total_equity += b["balance"]
        elif b["type"] == "income":
            accumulated_income += b["balance"]
        elif b["type"] == "expense":
            accumulated_expense += b["balance"]

    retained_earnings = accumulated_income - accumulated_expense
    if retained_earnings != 0:
        equity_rows.append(BalanceSheetRow(code="3100", name="Retained Earnings", balance=retained_earnings))
        total_equity += retained_earnings

    return BalanceSheetReport(
        asOf=effective_date,
        assets=BalanceSheetSection(label="Assets", rows=asset_rows, total=total_assets),
        liabilities=BalanceSheetSection(label="Liabilities", rows=liability_rows, total=total_liabilities),
        equity=BalanceSheetSection(label="Equity", rows=equity_rows, total=total_equity),
        totalAssets=total_assets, totalLiabilities=total_liabilities, totalEquity=total_equity,
    )


async def resolve_ar_aging(
    info: Info,
    asOf: Optional[date] = None,
    branchCode: Optional[str] = None,
) -> ARAgingReport:
    effective_date = asOf or date.today()
    user = info.context.get("current_user")
    effective_branch = branchCode or (get_sql_branch_filter(user) if user else None)

    session_factory = get_async_session_local()
    async with session_factory() as session:
        stmt = (
            select(
                AmortizationSchedule.loan_id,
                AmortizationSchedule.principal_due,
                AmortizationSchedule.interest_due,
                AmortizationSchedule.penalty_due,
                AmortizationSchedule.principal_paid,
                AmortizationSchedule.interest_paid,
                AmortizationSchedule.penalty_paid,
                AmortizationSchedule.due_date,
                LoanApplication.customer_id,
                LoanApplication.branch_code,
                Customer.display_name,
            )
            .select_from(AmortizationSchedule)
            .join(LoanApplication, LoanApplication.id == AmortizationSchedule.loan_id)
            .outerjoin(Customer, cast(LoanApplication.customer_id, Customer.id.type) == Customer.id)
            .where(AmortizationSchedule.status.in_(["pending", "partial", "overdue"]))
            .where(LoanApplication.status.notin_(["paid", "closed", "written_off"]))
            .where(AmortizationSchedule.due_date <= effective_date)
        )
        if effective_branch:
            stmt = stmt.where(LoanApplication.branch_code == effective_branch)
        rows = (await session.execute(stmt)).all()

    loan_data: Dict[str, dict] = {}
    for r in rows:
        lid = str(r.loan_id)
        if lid not in loan_data:
            loan_data[lid] = {
                "loan_id": lid, "customer_id": str(r.customer_id or "0"),
                "customer_name": r.display_name or f"Customer {r.customer_id}",
                "branch_code": r.branch_code or "",
                "total_due": Decimal("0.00"),
                "buckets": {"current": Decimal("0.00"), "1-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "90+": Decimal("0.00")},
            }
        outstanding = (
            Decimal(str(r.principal_due or 0)) + Decimal(str(r.interest_due or 0)) + Decimal(str(r.penalty_due or 0))
            - Decimal(str(r.principal_paid or 0)) - Decimal(str(r.interest_paid or 0)) - Decimal(str(r.penalty_paid or 0))
        )
        if outstanding <= 0:
            continue
        dpd = max(0, (effective_date - r.due_date).days)
        ld = loan_data[lid]
        ld["total_due"] += outstanding
        if dpd <= 0:
            ld["buckets"]["current"] += outstanding
        elif dpd <= 30:
            ld["buckets"]["1-30"] += outstanding
        elif dpd <= 60:
            ld["buckets"]["31-60"] += outstanding
        elif dpd <= 90:
            ld["buckets"]["61-90"] += outstanding
        else:
            ld["buckets"]["90+"] += outstanding

    bucket_totals = {"current": Decimal("0.00"), "1-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "90+": Decimal("0.00")}
    grand_total = Decimal("0.00")
    customer_rows: List[ARAgingCustomerRow] = []
    for ld in loan_data.values():
        if ld["total_due"] == 0:
            continue
        buckets_list = [
            ARAgingBucket(label="Current", amount=ld["buckets"]["current"]),
            ARAgingBucket(label="1-30 Days", amount=ld["buckets"]["1-30"]),
            ARAgingBucket(label="31-60 Days", amount=ld["buckets"]["31-60"]),
            ARAgingBucket(label="61-90 Days", amount=ld["buckets"]["61-90"]),
            ARAgingBucket(label="90+ Days", amount=ld["buckets"]["90+"]),
        ]
        customer_rows.append(ARAgingCustomerRow(
            customerId=ld["customer_id"], customerName=ld["customer_name"],
            loanId=ld["loan_id"], branchCode=ld["branch_code"],
            totalDue=ld["total_due"], buckets=buckets_list,
        ))
        grand_total += ld["total_due"]
        for k in bucket_totals:
            bucket_totals[k] += ld["buckets"][k]

    bucket_total_list = [
        ARAgingBucket(label="Current", amount=bucket_totals["current"]),
        ARAgingBucket(label="1-30 Days", amount=bucket_totals["1-30"]),
        ARAgingBucket(label="31-60 Days", amount=bucket_totals["31-60"]),
        ARAgingBucket(label="61-90 Days", amount=bucket_totals["61-90"]),
        ARAgingBucket(label="90+ Days", amount=bucket_totals["90+"]),
    ]

    return ARAgingReport(asOf=effective_date, rows=customer_rows, bucketTotals=bucket_total_list, grandTotal=grand_total, rowCount=len(customer_rows))


async def resolve_ap_aging(
    info: Info,
    asOf: Optional[date] = None,
    branchCode: Optional[str] = None,
) -> APAgingReport:
    effective_date = asOf or date.today()
    user = info.context.get("current_user")
    effective_branch = branchCode or (get_sql_branch_filter(user) if user else None)

    session_factory = get_async_session_local()
    async with session_factory() as session:
        from .database.pg_loan_models import LoanTransaction
        subq = (
            select(func.coalesce(func.sum(LoanTransaction.amount), 0))
            .where(
                LoanTransaction.loan_id == LoanApplication.id,
                LoanTransaction.type == "disbursement",
            )
            .scalar_subquery()
        )
        stmt = (
            select(
                LoanApplication.id,
                LoanApplication.approved_principal,
                LoanApplication.created_at,
                LoanApplication.branch_code,
                LoanApplication.customer_id,
                Customer.display_name,
                subq.label("total_disbursed"),
            )
            .select_from(LoanApplication)
            .outerjoin(Customer, cast(LoanApplication.customer_id, Customer.id.type) == Customer.id)
            .where(LoanApplication.status.in_(["approved", "active"]))
        )
        if effective_branch:
            stmt = stmt.where(LoanApplication.branch_code == effective_branch)
        rows = (await session.execute(stmt)).all()

    ap_rows: List[APAgingRow] = []
    bucket_totals = {"current": Decimal("0.00"), "1-30": Decimal("0.00"), "31-60": Decimal("0.00"), "61-90": Decimal("0.00"), "90+": Decimal("0.00")}
    grand_total = Decimal("0.00")

    for r in rows:
        approved = Decimal(str(r.approved_principal or 0))
        disbursed = Decimal(str(r.total_disbursed or 0))
        outstanding = approved - disbursed
        if outstanding <= 0:
            continue
        created = r.created_at.date() if isinstance(r.created_at, datetime) else r.created_at
        dpd = max(0, (effective_date - created).days)
        bucket = "current" if dpd <= 0 else "1-30" if dpd <= 30 else "31-60" if dpd <= 60 else "61-90" if dpd <= 90 else "90+"
        bucket_label = {"current": "Current", "1-30": "1-30 Days", "31-60": "31-60 Days", "61-90": "61-90 Days", "90+": "90+ Days"}[bucket]

        ap_rows.append(APAgingRow(
            referenceNo=f"LOAN-{r.id}", branchCode=r.branch_code or "", amount=outstanding,
            dueDate=created, agingBucket=bucket_label, daysPastDue=dpd,
            customerName=r.display_name or f"Customer {r.customer_id}", loanId=str(r.id),
            buckets=[],
        ))
        bucket_totals[bucket] += outstanding
        grand_total += outstanding

    bucket_total_list = [
        ARAgingBucket(label="Current", amount=bucket_totals["current"]),
        ARAgingBucket(label="1-30 Days", amount=bucket_totals["1-30"]),
        ARAgingBucket(label="31-60 Days", amount=bucket_totals["31-60"]),
        ARAgingBucket(label="61-90 Days", amount=bucket_totals["61-90"]),
        ARAgingBucket(label="90+ Days", amount=bucket_totals["90+"]),
    ]

    return APAgingReport(asOf=effective_date, rows=ap_rows, bucketTotals=bucket_total_list, grandTotal=grand_total, rowCount=len(ap_rows))
