"""
SQLAlchemy ORM models for Phase 1 PostgreSQL tables.
These complement the existing MongoDB collections (users, customers, loans, savings)
without replacing them. New Phase 1 features (audit, sessions, branches, KYC, etc.)
are stored in PostgreSQL for relational integrity.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Branch / Office
# ---------------------------------------------------------------------------
class Branch(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    contact_number = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# User → Branch Assignment (many-to-one: each user belongs to one branch)
# ---------------------------------------------------------------------------
class UserBranchAssignment(Base):
    __tablename__ = "user_branch_assignments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, unique=True, index=True)  # MongoDB _id
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    branch_code = Column(String(20), nullable=True, index=True)  # denormalized for fast lookups
    assigned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    assigned_by = Column(String(64), nullable=True)  # user_id of assigning admin

    branch = relationship("Branch", backref="user_assignments")

    __table_args__ = (
        Index("ix_user_branch_user_id", "user_id"),
        Index("ix_user_branch_branch_code", "branch_code"),
    )


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # MongoDB user _id (stored as string)
    user_id = Column(String(64), nullable=True, index=True)
    username = Column(String(100), nullable=True)
    role = Column(String(50), nullable=True)
    branch_code = Column(String(20), nullable=True, index=True)  # branch of the acting user
    action = Column(String(100), nullable=False)          # e.g. "create_customer"
    entity = Column(String(100), nullable=True)           # e.g. "customer"
    entity_id = Column(String(64), nullable=True)
    ip_address = Column(String(45), nullable=True)
    status = Column(String(20), nullable=False, default="success")  # success | failure
    detail = Column(Text, nullable=True)                  # JSON summary
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_branch", "branch_code"),
    )


# ---------------------------------------------------------------------------
# User Sessions (Redis-backed expiry, PG for audit / force-logout)
# ---------------------------------------------------------------------------
class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    jti = Column(String(64), nullable=False, unique=True)     # JWT ID claim
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_user_sessions_user_active", "user_id", "is_active"),
    )


# ---------------------------------------------------------------------------
# KYC Documents
# ---------------------------------------------------------------------------
class KYCDocument(Base):
    __tablename__ = "kyc_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Reference to MongoDB customer _id
    customer_id = Column(String(64), nullable=False, index=True)
    doc_type = Column(String(100), nullable=False)       # "government_id" | "proof_of_address" | "income_proof"
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=True)      # server-side path or S3 key
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default="pending")  # pending | verified | rejected
    reviewed_by = Column(String(64), nullable=True)      # user_id of reviewer
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Beneficiaries / Next of Kin
# ---------------------------------------------------------------------------
class Beneficiary(Base):
    __tablename__ = "beneficiaries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, index=True)
    full_name = Column(String(300), nullable=False)
    relationship = Column(String(100), nullable=False)       # "spouse" | "parent" | "sibling" | "child" | "other"
    birth_date = Column(DateTime(timezone=True), nullable=True)
    contact_number = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ---------------------------------------------------------------------------
# Customer Activity Log
# ---------------------------------------------------------------------------
class CustomerActivity(Base):
    __tablename__ = "customer_activities"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, index=True)
    actor_user_id = Column(String(64), nullable=True)
    actor_username = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False)           # "created" | "updated" | "kyc_submitted" | "kyc_verified" | etc.
    detail = Column(Text, nullable=True)                   # JSON string with changed fields
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (
        Index("ix_customer_activities_cust_created", "customer_id", "created_at"),
    )


# ---------------------------------------------------------------------------
# Password History (prevent reuse of last N passwords)
# ---------------------------------------------------------------------------
class PasswordHistory(Base):
    __tablename__ = "password_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "ix_password_history_user_created",
            "user_id",
            created_at.desc(),
        ),
    )


# ---------------------------------------------------------------------------
# AML Alerts (BSP Circular 1048, RA 9160)
# ---------------------------------------------------------------------------
class AMLAlert(Base):
    __tablename__ = "aml_alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, index=True)
    transaction_id = Column(String(64), nullable=True)
    alert_type = Column(String(50), nullable=False)  # "suspicious_activity", "ctr", "pep", "sar"
    severity = Column(String(20), nullable=False)  # "low", "medium", "high"
    description = Column(Text, nullable=True)
    reported_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    reported_by = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="pending_review")  # "pending_review", "investigated", "reported"
    requires_filing = Column(Boolean, default=False, nullable=False)
    ctr_amount = Column(Numeric(15, 2), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(String(64), nullable=True)
    
    __table_args__ = (
        Index("ix_aml_alerts_customer", "customer_id"),
        Index("ix_aml_alerts_type", "alert_type"),
        Index("ix_aml_alerts_status", "status"),
    )


# ---------------------------------------------------------------------------
# PEP Database (for reference - in production, integrate with external PEP databases)
# ---------------------------------------------------------------------------
class PEPRecord(Base):
    __tablename__ = "pep_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    position = Column(String(200), nullable=True)
    country = Column(String(100), nullable=True)
    pep_type = Column(String(50), nullable=True)  # "foreign_pep", "domestic_pep", "pep_associate"
    added_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


# ---------------------------------------------------------------------------
# Collections (loan repayment collections)
# ---------------------------------------------------------------------------
class Collection(Base):
    __tablename__ = "collections"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending, partial, collected, overdue, written_off
    due_date = Column(DateTime(timezone=True), nullable=False)
    collection_date = Column(DateTime(timezone=True), nullable=True)
    collected_by = Column(String(64), nullable=True)
    reference_number = Column(String(100), nullable=True)
    collection_type = Column(String(50), nullable=True)  # principal, interest, penalty
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_collections_due_date", "due_date"),
        Index("ix_collections_status", "status"),
    )
