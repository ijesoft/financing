from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


# ---------------------------------------------------------------------------
# Loan Products
# ---------------------------------------------------------------------------
class PGLoanProduct(Base):
    __tablename__ = "loan_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_code = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    amortization_type = Column(
        String(50), nullable=False
    )  # "flat_rate" | "declining_balance" | "balloon_payment" | "interest_only"
    repayment_frequency = Column(
        String(50), nullable=False
    )  # "daily" | "weekly" | "bi_weekly" | "monthly" | "quarterly" | "bullet"

    interest_rate = Column(
        Numeric(10, 4), nullable=False
    )  # Percentage (e.g., 5.0 for 5%)
    penalty_rate = Column(Numeric(10, 4), nullable=False, default=0.0)  # Percentage
    grace_period_months = Column(BigInteger, nullable=False, default=0)

    # Phase 2.1 Enhanced Features
    principal_only_grace = Column(
        Boolean, nullable=False, default=False
    )  # True for principal-only grace
    full_grace = Column(
        Boolean, nullable=False, default=False
    )  # True for full grace period
    origination_fee_rate = Column(
        Numeric(10, 4), nullable=True
    )  # Percentage for origination fee
    origination_fee_type = Column(String(50), nullable=True)  # "upfront" | "spread"
    prepayment_allowed = Column(
        Boolean, nullable=False, default=True
    )  # True if prepayment allowed
    prepayment_penalty_rate = Column(
        Numeric(10, 4), nullable=True
    )  # Percentage for prepayment penalty
    customer_loan_limit = Column(
        Numeric(14, 2), nullable=True
    )  # Maximum borrowing per customer (0 = unlimited)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Loan Applications
# ---------------------------------------------------------------------------
class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Mongo references
    customer_id = Column(String(64), nullable=False, index=True)
    branch_code = Column(String(20), nullable=True, index=True)  # branch that originated the loan

    # Relations
    product_id = Column(BigInteger, ForeignKey("loan_products.id"), nullable=False)
    product = relationship("PGLoanProduct")

    # Application Details
    principal = Column(Numeric(14, 2), nullable=False)
    term_months = Column(BigInteger, nullable=False)

    # Approval Details
    approved_principal = Column(Numeric(14, 2), nullable=True)
    approved_rate = Column(Numeric(10, 4), nullable=True)

    status = Column(String(50), nullable=False, default="draft")
    # Statuses: draft, submitted, reviewing, approved, active, paid, rejected, defaulted, non_accrual, written_off

    is_npl = Column(Boolean, nullable=False, default=False, index=True)
    non_accrual_since = Column(DateTime(timezone=True), nullable=True)
    collections_officer = Column(String(64), nullable=True)
    assigned_collections_branch = Column(String(20), nullable=True, index=True)
    ecl_stage = Column(String(10), nullable=True, default="S1")

    review_note = Column(Text, nullable=True)
    disbursement_method = Column(
        String(50), nullable=True
    )  # cash | bank_transfer | cheque | savings_transfer

    # Phase 2.2 — Approval workflow tracking
    reviewed_by = Column(
        String(64), nullable=True
    )  # mongo user_id of reviewer (loan officer)
    approved_by = Column(
        String(64), nullable=True
    )  # mongo user_id of approver (branch manager/admin)
    rejected_reason = Column(Text, nullable=True)  # reason for rejection

    # Extended tracking
    outstanding_balance = Column(Numeric(14, 2), nullable=True)
    next_due_date = Column(DateTime(timezone=True), nullable=True)
    months_paid = Column(Integer, nullable=True, default=0)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    disbursed_at = Column(DateTime(timezone=True), nullable=True)

    schedules = relationship(
        "AmortizationSchedule", back_populates="loan", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Loan Collateral
# ---------------------------------------------------------------------------
class LoanCollateral(Base):
    __tablename__ = "loan_collateral"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    type = Column(String(100), nullable=False)  # "vehicle" | "real_estate" | "deposit"
    value = Column(Numeric(14, 2), nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Loan Guarantors
# ---------------------------------------------------------------------------
class LoanGuarantor(Base):
    __tablename__ = "loan_guarantors"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    # Mongo reference
    customer_id = Column(String(64), nullable=False, index=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Amortization Schedule
# ---------------------------------------------------------------------------
class AmortizationSchedule(Base):
    __tablename__ = "amortization_schedules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )
    loan = relationship("LoanApplication", back_populates="schedules")

    installment_number = Column(BigInteger, nullable=False)
    due_date = Column(Date, nullable=False)

    # Expected
    principal_due = Column(Numeric(14, 2), nullable=False)
    interest_due = Column(Numeric(14, 2), nullable=False)
    penalty_due = Column(Numeric(14, 2), nullable=False, default=0)

    # Actual payments applied
    principal_paid = Column(Numeric(14, 2), nullable=False, default=0)
    interest_paid = Column(Numeric(14, 2), nullable=False, default=0)
    penalty_paid = Column(Numeric(14, 2), nullable=False, default=0)

    # Payment date (when the installment was paid)
    payment_date = Column(DateTime(timezone=True), nullable=True)

    status = Column(String(50), nullable=False, default="pending")
    # pending, partial, paid, overdue

    UNIQUE_CONSTRAINT = UniqueConstraint(
        "loan_id", "installment_number", name="uq_loan_installment"
    )


# ---------------------------------------------------------------------------
# Loan Transactions
# ---------------------------------------------------------------------------
class LoanTransaction(Base):
    __tablename__ = "loan_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    type = Column(String(50), nullable=False)  # "disbursement" | "repayment" | "fee"
    amount = Column(Numeric(14, 2), nullable=False)

    receipt_number = Column(String(100), nullable=True, unique=True)
    description = Column(Text, nullable=True)

    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_by = Column(String(64), nullable=True)  # mongo user id

    # Ported from master branch
    commercial_bank = Column(String(100), nullable=True)
    servicing_branch = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    loan_product_id = Column(String(100), nullable=True)
    debit_account = Column(String(100), nullable=True)
    credit_account = Column(String(100), nullable=True)
    disbursement_method = Column(String(100), nullable=True)
    disbursement_status = Column(String(50), nullable=True, default="pending")
    cheque_number = Column(String(100), nullable=True)
    beneficiary_bank = Column(String(100), nullable=True)
    beneficiary_account = Column(String(100), nullable=True)
    approved_by = Column(String(64), nullable=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    borrower_name = Column(String(200), nullable=True)
    is_eft = Column(Boolean, nullable=True, default=False)
    
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Credit Scoring (5 Cs)
# ---------------------------------------------------------------------------
class CreditScore(Base):
    __tablename__ = "credit_scores"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    # Character - credit history assessment
    character_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    character_notes = Column(Text, nullable=True)

    # Capacity - ability to repay
    capacity_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    capacity_notes = Column(Text, nullable=True)

    # Capital - financial reserves
    capital_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    capital_notes = Column(Text, nullable=True)

    # Collateral - security offered
    collateral_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    collateral_notes = Column(Text, nullable=True)

    # Conditions - economic conditions
    conditions_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    conditions_notes = Column(Text, nullable=True)

    # Overall score (weighted average)
    overall_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    recommendation = Column(
        String(50), nullable=True
    )  # "approve" | "review" | "reject"

    dti_ratio = Column(Numeric(10, 4), nullable=True)  # Debt-to-Income ratio
    dti_score = Column(Numeric(5, 2), nullable=True)  # 0-100

    assessed_by = Column(String(64), nullable=True)
    assessed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Loan Application Documents
# ---------------------------------------------------------------------------
class LoanApplicationDocument(Base):
    __tablename__ = "loan_application_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    doc_type = Column(
        String(100), nullable=False
    )  # "payslip" | "itr" | "coe" | "bank_statement" | "other"
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    mime_type = Column(String(100), nullable=True)

    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending | verified | rejected
    rejection_reason = Column(Text, nullable=True)

    uploaded_by = Column(String(64), nullable=True)
    verified_by = Column(String(64), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Disbursement Checklist
# ---------------------------------------------------------------------------
class DisbursementChecklist(Base):
    __tablename__ = "disbursement_checklist"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    item_name = Column(String(200), nullable=False)
    item_description = Column(Text, nullable=True)
    is_required = Column(Boolean, nullable=False, default=True)

    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending | satisfied | waived
    notes = Column(Text, nullable=True)
    satisfied_by = Column(String(64), nullable=True)
    satisfied_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Partial Disbursement (Tranches)
# ---------------------------------------------------------------------------
class LoanTranche(Base):
    __tablename__ = "loan_tranches"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    tranche_number = Column(BigInteger, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    release_date = Column(DateTime(timezone=True), nullable=True)

    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending | released | cancelled
    released_by = Column(String(64), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Promise-to-Pay (PTP) Tracking
# ---------------------------------------------------------------------------
class PromiseToPay(Base):
    __tablename__ = "promise_to_pay"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    ptp_date = Column(Date, nullable=False)
    ptp_amount = Column(Numeric(14, 2), nullable=False)

    contact_method = Column(
        String(50), nullable=True
    )  # "phone" | "email" | "sms" | "in_person"
    contact_attempted = Column(BigInteger, nullable=False, default=0)
    contact_result = Column(Text, nullable=True)  # notes on the conversation

    status = Column(
        String(50), nullable=False, default="pending"
    )  # pending | broken | fulfilled | cancelled
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)
    broken_reason = Column(Text, nullable=True)

    created_by = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Loan Restructure Log
# ---------------------------------------------------------------------------
class LoanRestructureLog(Base):
    __tablename__ = "loan_restructure_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    loan_id = Column(
        BigInteger, ForeignKey("loan_applications.id"), nullable=False, index=True
    )

    old_term_months = Column(BigInteger, nullable=False)
    old_interest_rate = Column(Numeric(10, 4), nullable=False)
    old_principal = Column(Numeric(14, 2), nullable=False)

    new_term_months = Column(BigInteger, nullable=False)
    new_interest_rate = Column(Numeric(10, 4), nullable=False)
    new_principal = Column(Numeric(14, 2), nullable=False)

    capitalize_arrears = Column(Boolean, nullable=False, default=False)
    arrears_amount = Column(Numeric(14, 2), nullable=True)

    reason = Column(Text, nullable=True)

    created_by = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
