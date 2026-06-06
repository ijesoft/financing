from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class GLAccount(Base):
    __tablename__ = "gl_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    reference_no = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(64), nullable=True)
    value_date = Column(Date, nullable=True)
    branch_id = Column(BigInteger, nullable=True, index=True)
    branch_code = Column(String(20), nullable=True, index=True)
    idempotency_key = Column(String(64), nullable=True, unique=True)
    loan_id = Column(BigInteger, nullable=True, index=True)
    customer_id = Column(String(64), nullable=True, index=True)
    prev_hash = Column(String(64), nullable=True)
    row_hash = Column(String(64), nullable=False, default="")
    lines = relationship(
        "JournalLine",
        back_populates="entry",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_journal_entries_created", "timestamp"),
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    entry_id = Column(BigInteger, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, index=True)
    entry = relationship("JournalEntry", back_populates="lines")
    account_code = Column(String(50), ForeignKey("gl_accounts.code"), nullable=False, index=True)
    account = relationship("GLAccount")
    debit = Column(Numeric(16, 2), nullable=False, default=0)
    credit = Column(Numeric(16, 2), nullable=False, default=0)
    description = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_journal_lines_acct_entry", "account_code", "entry_id"),
        Index("ix_journal_lines_entry", "entry_id"),
    )


class TransactionIdempotency(Base):
    __tablename__ = "transaction_idempotency"

    idempotency_key = Column(String(64), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    response_json = Column(Text, nullable=False)
    status_code = Column(BigInteger, nullable=False, default=200)
    journal_entry_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_transaction_idempotency_expires", "expires_at"),
    )
