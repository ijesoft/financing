"""
BE-08: amortization schedule persistence.

These are pure-function tests for the schedule builders; full DB persistence
is exercised by `test_loan_accounting.py` (repayment writes back to schedule).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.amortization_service import (
    build_balloon_schedule,
    build_declining_schedule,
    build_flat_schedule,
    build_interest_only_schedule,
    build_schedule,
)


def test_flat_schedule_sum_matches_principal_plus_interest():
    rows = build_flat_schedule(
        principal=Decimal("12000.00"),
        annual_rate_pct=Decimal("12"),
        term_months=12,
        start_date=date(2026, 1, 1),
    )
    assert len(rows) == 12
    total_p = sum((r["principal_due"] for r in rows))
    total_i = sum((r["interest_due"] for r in rows))
    assert total_p == 1200000
    assert total_i > 0


def test_declining_schedule_pays_principal():
    rows = build_declining_schedule(
        principal=Decimal("12000.00"),
        annual_rate_pct=Decimal("12"),
        term_months=12,
        start_date=date(2026, 1, 1),
    )
    assert len(rows) == 12
    assert rows[0]["interest_due"] > rows[-1]["interest_due"]
    assert rows[0]["principal_due"] < rows[-1]["principal_due"]


def test_interest_only_schedule_principal_only_at_end():
    rows = build_interest_only_schedule(
        principal=Decimal("12000.00"),
        annual_rate_pct=Decimal("12"),
        term_months=12,
        start_date=date(2026, 1, 1),
    )
    assert len(rows) == 12
    for r in rows[:-1]:
        assert r["principal_due"] == 0
    assert rows[-1]["principal_due"] == 1200000


def test_balloon_schedule_principal_only_at_end():
    rows = build_balloon_schedule(
        principal=Decimal("12000.00"),
        annual_rate_pct=Decimal("12"),
        term_months=12,
        start_date=date(2026, 1, 1),
    )
    assert len(rows) == 12
    for r in rows[:-1]:
        assert r["principal_due"] == 0
    assert rows[-1]["principal_due"] == 1200000


def test_build_schedule_dispatch():
    rows = build_schedule("flat_rate", Decimal("1000"), Decimal("12"), 6, date(2026, 1, 1))
    assert len(rows) == 6
    with pytest.raises(ValueError):
        build_schedule("unknown_type", Decimal("1000"), Decimal("12"), 6, date(2026, 1, 1))
