"""
Collections Due + Aging Report GraphQL schema (Strawberry).

This module is wired into the main `Query` type by the
`register_collections_queries` helper at the bottom of this file.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

import strawberry


@strawberry.enum
class AgingBucket(Enum):
    CURRENT = "current"
    DPD_1_30 = "1-30"
    DPD_31_60 = "31-60"
    DPD_61_90 = "61-90"
    DPD_91_180 = "91-180"
    DPD_180_PLUS = "180+"


@strawberry.enum
class ECLStage(Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"


@strawberry.type
class CollectionsDueEntry:
    loan_id: strawberry.ID = strawberry.field(name="loanId")
    customer_id: strawberry.ID = strawberry.field(name="customerId")
    customer_name: str = strawberry.field(name="customerName")
    branch_code: Optional[str] = strawberry.field(name="branchCode")
    installment_no: int = strawberry.field(name="installmentNo")
    due_date: date = strawberry.field(name="dueDate")
    principal_due: Decimal = strawberry.field(name="principalDue")
    interest_due: Decimal = strawberry.field(name="interestDue")
    penalty_due: Decimal = strawberry.field(name="penaltyDue")
    fee_due: Decimal = strawberry.field(name="feeDue")
    total_due: Decimal = strawberry.field(name="totalDue")
    amount_paid: Decimal = strawberry.field(name="amountPaid")
    balance_due: Decimal = strawberry.field(name="balanceDue")
    dpd: int
    aging_bucket: AgingBucket = strawberry.field(name="agingBucket")
    ecl_stage: ECLStage = strawberry.field(name="eclStage")
    is_npl: bool = strawberry.field(name="isNpl")
    collections_officer: Optional[str] = strawberry.field(name="collectionsOfficer")
    assigned_collections_branch: Optional[str] = strawberry.field(name="assignedCollectionsBranch")
    mobile_number: Optional[str] = strawberry.field(name="mobileNumber")


@strawberry.type
class CollectionsDueReport:
    as_of: date = strawberry.field(name="asOf")
    branch_code: Optional[str] = strawberry.field(name="branchCode")
    total_entries: int = strawberry.field(name="totalEntries")
    total_principal_due: Decimal = strawberry.field(name="totalPrincipalDue")
    total_interest_due: Decimal = strawberry.field(name="totalInterestDue")
    total_penalty_due: Decimal = strawberry.field(name="totalPenaltyDue")
    total_fee_due: Decimal = strawberry.field(name="totalFeeDue")
    total_balance_due: Decimal = strawberry.field(name="totalBalanceDue")
    entries: List[CollectionsDueEntry]


@strawberry.type
class CollectionsDueSummary:
    as_of: date = strawberry.field(name="asOf")
    branch_code: Optional[str] = strawberry.field(name="branchCode")
    total_overdue_loans: int = strawberry.field(name="totalOverdueLoans")
    total_overdue_amount: Decimal = strawberry.field(name="totalOverdueAmount")
    total_principal_overdue: Decimal = strawberry.field(name="totalPrincipalOverdue")
    total_interest_overdue: Decimal = strawberry.field(name="totalInterestOverdue")
    total_penalty_overdue: Decimal = strawberry.field(name="totalPenaltyOverdue")


@strawberry.type
class AgingBucketSummary:
    bucket: AgingBucket
    loan_count: int = strawberry.field(name="loanCount")
    outstanding_principal: Decimal = strawberry.field(name="outstandingPrincipal")
    pct_of_portfolio: float = strawberry.field(name="pctOfPortfolio")
    is_npl: bool = strawberry.field(name="isNpl")


@strawberry.type
class AgingReport:
    as_of: date = strawberry.field(name="asOf")
    branch_code: Optional[str] = strawberry.field(name="branchCode")
    total_outstanding: Decimal = strawberry.field(name="totalOutstanding")
    npl_ratio: float = strawberry.field(name="nplRatio")
    par30_ratio: float = strawberry.field(name="par30Ratio")
    buckets: List[AgingBucketSummary]
