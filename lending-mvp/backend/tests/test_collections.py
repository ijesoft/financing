"""
Collections Due + Aging Report tests.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database.pg_core_models import Customer
from app.database.pg_loan_models import (
    AmortizationSchedule,
    LoanApplication,
    PGLoanProduct,
)
from app.database.pg_models import Branch
from app.graphql_collections_resolvers import (
    resolve_aging_report,
    resolve_collections_due,
    resolve_collections_due_summary,
)


class _FakeInfo:
    def __init__(self, user):
        self.context = {"current_user": user}


class _FakeUser:
    def __init__(self, role, branch_code=None):
        self.role = role
        self.branch_code = branch_code
        self.username = "tester"


async def _seed_loan_with_overdue(db_session, *, dpd, principal_due=100000, interest_due=5000, penalty_due=0):
    branch = Branch(
        code=f"HQ-{uuid.uuid4().hex[:6]}",
        name="HQ Test Branch",
        is_active=True,
    )
    db_session.add(branch)
    await db_session.flush()

    prod = PGLoanProduct(
        product_code=f"COLL-{uuid.uuid4().hex[:6]}",
        name="Coll Test",
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

    customer = Customer(
        customer_type="individual",
        last_name="CollTest",
        first_name="Loan",
        display_name=f"Coll Test Loan {uuid.uuid4().hex[:6]}",
        mobile_number="09170000000",
        branch_id=branch.id,
        branch_code=branch.code,
    )
    db_session.add(customer)
    await db_session.flush()

    loan = LoanApplication(
        customer_id=str(customer.id),
        branch_code=branch.code,
        product_id=prod.id,
        principal=Decimal("10000.00"),
        term_months=12,
        status="active",
    )
    db_session.add(loan)
    await db_session.flush()

    due = date.today() - timedelta(days=dpd)
    sched = AmortizationSchedule(
        loan_id=loan.id,
        installment_number=1,
        due_date=due,
        principal_due=Decimal(principal_due) / Decimal(100),
        interest_due=Decimal(interest_due) / Decimal(100),
        principal_paid=Decimal("0.00"),
        interest_paid=Decimal("0.00"),
        penalty_due=Decimal(penalty_due) / Decimal(100),
        penalty_paid=Decimal("0.00"),
        status="pending",
    )
    db_session.add(sched)
    await db_session.flush()
    return loan, branch


@pytest.mark.asyncio
async def test_collections_due_today(db_session):
    loan, branch = await _seed_loan_with_overdue(db_session, dpd=0)
    await db_session.commit()
    user = _FakeUser("admin", branch_code=None)
    info = _FakeInfo(user)
    report = await resolve_collections_due(info, as_of=date.today(), branch_code=branch.code, limit=100, offset=0)
    assert any(str(e.loan_id) == str(loan.id) for e in report.entries)


@pytest.mark.asyncio
async def test_collections_due_bucket_assignment(db_session):
    loans = []
    branch = None
    for dpd in (0, 15, 45, 75, 120, 200):
        loan, b = await _seed_loan_with_overdue(db_session, dpd=dpd)
        loans.append(loan)
        branch = b
    await db_session.commit()

    info = _FakeInfo(_FakeUser("admin"))
    report = await resolve_collections_due(info, as_of=date.today(), branch_code=branch.code, limit=200, offset=0)
    seen_buckets = {e.aging_bucket.value for e in report.entries}
    assert "current" in seen_buckets
    assert "1-30" in seen_buckets
    assert "31-60" in seen_buckets
    assert "61-90" in seen_buckets
    assert "91-180" in seen_buckets
    assert "180+" in seen_buckets


@pytest.mark.asyncio
async def test_aging_report_par30_and_npl(db_session):
    branch = None
    for dpd in (0, 45, 120):
        _, _b = await _seed_loan_with_overdue(db_session, dpd=dpd)
        branch = _b
    await db_session.commit()
    info = _FakeInfo(_FakeUser("admin"))
    rep = await resolve_aging_report(info, as_of=date.today(), branch_code=branch.code)
    assert rep.total_outstanding > 0
    assert rep.par30_ratio > 0
    assert rep.npl_ratio > 0
    npl_buckets = [b for b in rep.buckets if b.is_npl]
    assert len(npl_buckets) > 0


@pytest.mark.asyncio
async def test_collections_due_rbac_denies_customer(db_session):
    info = _FakeInfo(_FakeUser("customer", branch_code=None))
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await resolve_collections_due(info, as_of=date.today(), branch_code="HQ")


@pytest.mark.asyncio
async def test_aging_report_rbac_denies_loan_officer(db_session):
    info = _FakeInfo(_FakeUser("loan_officer", branch_code="HQ"))
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await resolve_aging_report(info, as_of=date.today(), branch_code="HQ")
