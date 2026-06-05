"""
Core PostgreSQL models for Phase 2 migration.
Replaces MongoDB documents with relational tables for:
- users
- customers
- savings accounts
- transactions
- ledger entries
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

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
    func,
)
from sqlalchemy.orm import relationship

from .base import Base
from .pg_loan_models import PGLoanProduct
# Import Branch and GLAccount directly to avoid circular dependencies
# They are defined later in the file


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Users - Replaces MongoDB users collection
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    uuid = Column(String(36), default=lambda: str(uuid4()), unique=True)
    
    email = Column(String(200), nullable=False, unique=True)
    username = Column(String(100), nullable=False, unique=True)
    full_name = Column(String(200), nullable=False)
    hashed_password = Column(String(200), nullable=False)
    role = Column(String(50), nullable=False)  # "admin", "manager", "staff", "teller"
    
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True, index=True)
    branch_code = Column(String(20), nullable=True, index=True)  # denormalized for performance
    
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )


# ---------------------------------------------------------------------------
# Customers - Replaces MongoDB customers collection
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    customer_type = Column(String(50), nullable=False)  # "individual", "corporate"
    
    # Individual fields
    last_name = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    middle_name = Column(String(100), nullable=True)
    display_name = Column(String(300), nullable=False, index=True)
    
    # Identification
    tin_no = Column(String(50), nullable=True)
    sss_no = Column(String(50), nullable=True)
    
    # Personal info
    birth_date = Column(Date, nullable=True)
    birth_place = Column(String(200), nullable=True)
    
    # Contact
    mobile_number = Column(String(50), nullable=True, index=True)
    email_address = Column(String(200), nullable=True)
    
    # Address
    permanent_address = Column(Text, nullable=True)
    
    # Employment (for individuals)
    employer_name_address = Column(Text, nullable=True)
    job_title = Column(String(100), nullable=True)
    salary_range = Column(String(50), nullable=True)
    
    # Company info (for corporate)
    company_name = Column(String(200), nullable=True)
    company_address = Column(Text, nullable=True)
    
    # Branch association
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    branch_code = Column(String(20), nullable=False, index=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )
    
    savings_accounts = relationship("SavingsAccount", back_populates="customer", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Savings Accounts - Replaces MongoDB savings collection
# ---------------------------------------------------------------------------
class SavingsAccount(Base):
    __tablename__ = "savings_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    account_number = Column(String(50), nullable=False, unique=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), nullable=False, index=True)
    customer = relationship("Customer", back_populates="savings_accounts")
    
    account_type = Column(String(50), nullable=False)  # "regular", "fixed", "salary"
    
    balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    currency = Column(String(3), default="PHP", nullable=False)
    
    status = Column(String(20), default="active", nullable=False)
    
    interest_rate = Column(Numeric(5, 2), default=0.00)
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Ported from master branch
    maturity_date = Column(DateTime(timezone=True), nullable=True)
    principal = Column(Numeric(15, 2), nullable=True)
    term_days = Column(Integer, nullable=True)
    interest_paid_frequency = Column(String(50), nullable=True)
    target_amount = Column(Numeric(15, 2), nullable=True)
    target_date = Column(DateTime(timezone=True), nullable=True)
    goal_name = Column(String(200), nullable=True)
    guardian_id = Column(String(64), nullable=True)
    guardian_name = Column(String(200), nullable=True)
    minor_date_of_birth = Column(DateTime(timezone=True), nullable=True)
    secondary_owner_id = Column(String(64), nullable=True)
    secondary_owner_name = Column(String(200), nullable=True)
    operation_mode = Column(String(50), nullable=True, default="EITHER")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )
    
    transactions = relationship("SavingsTransaction", back_populates="account", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Savings Transactions - Replaces MongoDB savings transactions collection
# ---------------------------------------------------------------------------
class SavingsTransaction(Base):
    __tablename__ = "savings_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, ForeignKey("savings_accounts.id"), nullable=False, index=True)
    account = relationship("SavingsAccount", back_populates="transactions")
    
    transaction_type = Column(String(20), nullable=False)  # "deposit", "withdrawal"
    amount = Column(Numeric(15, 2), nullable=False)
    
    balance_before = Column(Numeric(15, 2), nullable=False)
    balance_after = Column(Numeric(15, 2), nullable=False)
    
    reference = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Standing Orders - Recurring payments
# ---------------------------------------------------------------------------
class StandingOrder(Base):
    __tablename__ = "standing_orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    account_id = Column(BigInteger, ForeignKey("savings_accounts.id"), nullable=False, index=True)
    account = relationship("SavingsAccount", backref="standing_orders")
    
    recipient_account = Column(String(50), nullable=False)
    recipient_name = Column(String(200), nullable=False)
    
    amount = Column(Numeric(15, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # "daily", "weekly", "monthly"
    
    next_execution_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )



