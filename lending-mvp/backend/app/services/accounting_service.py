"""
Double-entry accounting service.

Posts balanced journal entries (one debit + one credit line per entry)
to the `journal_entries` / `journal_lines` tables. The orphaned
`pg_core_models.LedgerEntry` model is intentionally NOT used — it
describes a different schema and the columns it claims to expose no
longer match the production table.
"""
from datetime import datetime
from decimal import Decimal
import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..database.pg_accounting_models import JournalEntry, JournalLine, GLAccount


async def post_transaction(
    db: AsyncSession,
    debit_account: str,
    credit_account: str,
    amount: Decimal,
    tx_id: str = None,
    branch_id: int = 1,
    branch_code: str = "HQ",
    description: str = None,
) -> bool:
    """
    Posts a balanced debit/credit transaction atomically.

    Returns True on commit, raises on validation failure or imbalance.
    Never silently rolls back; callers should treat an exception as a
    failed post.
    """
    if amount is None or Decimal(amount) <= 0:
        raise ValueError("Transaction amount must be positive.")

    amount_dec = Decimal(amount)
    transaction_id = tx_id or str(uuid.uuid4())

    if not description:
        description = f"Transaction {transaction_id}"

    try:
        # Create journal entry
        journal_entry = JournalEntry(
            reference_no=transaction_id,
            description=description,
        )
        db.add(journal_entry)
        await db.flush()

        # Create debit journal line
        debit_line = JournalLine(
            entry_id=journal_entry.id,
            account_code=debit_account,
            debit=amount_dec,
            credit=Decimal("0"),
            description=f"Debit {debit_account}",
        )
        db.add(debit_line)

        # Create credit journal line
        credit_line = JournalLine(
            entry_id=journal_entry.id,
            account_code=credit_account,
            debit=Decimal("0"),
            credit=amount_dec,
            description=f"Credit {credit_account}",
        )
        db.add(credit_line)

        # Assert balanced before commit (per-entry SUM(debit)=SUM(credit)).
        # Use the in-memory debit/credit on the lines we just built to
        # avoid the lazy-load + greenlet dance.
        d = (debit_line.debit or Decimal("0")) + (credit_line.debit or Decimal("0"))
        c = (debit_line.credit or Decimal("0")) + (credit_line.credit or Decimal("0"))
        if d != c or d == 0:
            raise ValueError(
                f"Unbalanced journal entry: debit={d} credit={c} for {transaction_id}"
            )

        await db.commit()
        return True

    except Exception as e:
        await db.rollback()
        # Re-raise so callers know the post failed.
        raise


async def get_ledger_entries_for_account(db: AsyncSession, account_code: str, limit: int = 100) -> List[dict]:
    """
    Return recent journal lines for an account.

    NOTE: the legacy `LedgerEntry` model is no longer maintained; we
    surface journal lines as the authoritative ledger view instead.
    """
    stmt = (
        select(JournalLine)
        .where(JournalLine.account_code == account_code)
        .order_by(JournalLine.entry_id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    lines = result.scalars().all()

    return [
        {
            "id": line.id,
            "entry_id": line.entry_id,
            "account_code": line.account_code,
            "debit": float(line.debit or 0),
            "credit": float(line.credit or 0),
            "description": line.description,
        }
        for line in lines
    ]


async def get_journal_entries_for_account(db: AsyncSession, account_code: str, limit: int = 100) -> List[dict]:
    """
    Return recent journal entries that touch a given account.
    """
    stmt = (
        select(JournalLine)
        .where(JournalLine.account_code == account_code)
        .order_by(JournalLine.entry_id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    lines = result.scalars().all()

    entry_ids = [line.entry_id for line in lines]
    if not entry_ids:
        return []

    stmt_entries = (
        select(JournalEntry)
        .where(JournalEntry.id.in_(entry_ids))
        .order_by(JournalEntry.id.desc())
    )
    result_entries = await db.execute(stmt_entries)
    journal_entries = result_entries.scalars().all()

    return [
        {
            "id": entry.id,
            "reference_no": entry.reference_no,
            "description": entry.description,
            "timestamp": entry.timestamp,
            "lines": [
                {
                    "account_code": line.account_code,
                    "debit": float(line.debit or 0),
                    "credit": float(line.credit or 0),
                }
                for line in entry.lines
            ],
        }
        for entry in journal_entries
    ]
