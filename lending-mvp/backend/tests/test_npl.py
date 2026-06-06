"""
BE-10: NPL service tests.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.loan_accounting_service import post_loan_repayment
from app.services.npl_service import (
    NPL_DPD_THRESHOLD,
    SICR_DPD_THRESHOLD,
    assess_npl_status,
    should_accrue_interest,
)


@pytest.mark.asyncio
async def test_be10_npl_flag_at_90_dpd(db_session):
    from app.database.pg_loan_models import AmortizationSchedule, LoanApplication, PGLoanProduct

    prod = PGLoanProduct(
        product_code=f"NPLPROD-{uuid.uuid4().hex[:6]}",
        name="NPL Test Product",
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
        customer_id="C-NPL-1",
        branch_code="HQ",
        product_id=prod.id,
        principal=Decimal("10000.00"),
        term_months=12,
        status="active",
    )
    db_session.add(loan)
    await db_session.flush()

    today = date.today()
    sched = AmortizationSchedule(
        loan_id=loan.id,
        installment_number=1,
        due_date=today - timedelta(days=95),
        principal_due=Decimal("1000.00"),
        interest_due=Decimal("50.00"),
        principal_paid=Decimal("0.00"),
        interest_paid=Decimal("0.00"),
        penalty_due=Decimal("0.00"),
        penalty_paid=Decimal("0.00"),
        status="pending",
    )
    db_session.add(sched)
    await db_session.flush()

    summary = await assess_npl_status(db_session, as_of=today)
    assert summary["npl_count"] >= 1
    assert summary["newly_npl"] >= 1

    result = await db_session.execute(
        text("SELECT is_npl, ecl_stage FROM loan_applications WHERE id=:i"),
        {"i": loan.id},
    )
    is_npl, ecl_stage = result.one()
    assert is_npl is True
    assert ecl_stage == "S3"
    assert should_accrue_interest(loan) is False


@pytest.mark.asyncio
async def test_be10_s2_at_30_dpd(db_session):
    from app.database.pg_loan_models import AmortizationSchedule, LoanApplication, PGLoanProduct

    prod = PGLoanProduct(
        product_code=f"S2PROD-{uuid.uuid4().hex[:6]}",
        name="S2 Test Product",
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
        customer_id="C-S2-1",
        branch_code="HQ",
        product_id=prod.id,
        principal=Decimal("10000.00"),
        term_months=12,
        status="active",
    )
    db_session.add(loan)
    await db_session.flush()

    today = date.today()
    sched = AmortizationSchedule(
        loan_id=loan.id,
        installment_number=1,
        due_date=today - timedelta(days=45),
        principal_due=Decimal("1000.00"),
        interest_due=Decimal("50.00"),
        principal_paid=Decimal("0.00"),
        interest_paid=Decimal("0.00"),
        penalty_due=Decimal("0.00"),
        penalty_paid=Decimal("0.00"),
        status="pending",
    )
    db_session.add(sched)
    await db_session.flush()

    summary = await assess_npl_status(db_session, as_of=today)
    assert summary["s2_count"] >= 1

    result = await db_session.execute(
        text("SELECT is_npl, ecl_stage FROM loan_applications WHERE id=:i"),
        {"i": loan.id},
    )
    is_npl, ecl_stage = result.one()
    assert is_npl is False
    assert ecl_stage == "S2"
    assert should_accrue_interest(loan) is True
