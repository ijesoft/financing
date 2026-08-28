"""
PostgreSQL-only transaction CRUD.

Replaces Mongo-based TransactionCRUD. All writes go to savings_transactions
via AsyncSession with SELECT FOR UPDATE and Decimal amounts.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .pg_core_models import SavingsAccount, SavingsTransaction


class TransactionCRUD:
    """PG-only CRUD for savings_transactions."""

    def __init__(self, db: AsyncSession, savings_crud=None):
        # savings_crud kept for backward compatibility but unused (balance handled here)
        self.db = db
        self.savings_crud = savings_crud

    async def create_transaction(
        self,
        account_id: int,
        transaction_type: str,
        amount: Decimal,
        reference: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[SavingsTransaction]:
        """
        Atomic: SELECT FOR UPDATE account, validate, update balance, insert transaction.

        transaction_type: 'deposit' | 'withdrawal' | 'transfer_in' | 'transfer_out' | 'interest_posting'
        amount must be Decimal > 0.
        """
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        if amount <= Decimal("0.00"):
            return None
        try:
            aid = int(str(account_id))
        except ValueError:
            return None

        # Lock account row
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == aid).with_for_update()
        )
        account = result.scalar_one_or_none()
        if not account:
            return None

        current = account.balance or Decimal("0.00")
        if not isinstance(current, Decimal):
            current = Decimal(str(current))

        # Validate withdrawal
        if transaction_type in ("withdrawal", "transfer_out"):
            if current < amount:
                return None
            # Regular savings minimum balance PHP 500
            if account.account_type == "regular" and (current - amount) < Decimal("500.00"):
                return None
            new_balance = current - amount
        else:
            # deposit / transfer_in / interest
            new_balance = current + amount

        balance_before = current
        balance_after = new_balance

        # Update account
        account.balance = new_balance
        await self.db.flush()

        # Insert transaction
        txn = SavingsTransaction(
            account_id=aid,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reference=reference,
            description=description,
        )
        self.db.add(txn)
        await self.db.flush()
        await self.db.refresh(txn)
        return txn

    # Backward-compatible wrapper for basemodel TransactionBase callers
    async def create_transaction_legacy(self, transaction) -> Optional[SavingsTransaction]:
        """Accepts old TransactionBase (Mongo) shape and delegates to PG method."""
        try:
            ttype = getattr(transaction, "transaction_type", None) or getattr(transaction, "type", "deposit")
            amt = getattr(transaction, "amount", Decimal("0.00"))
            aid = getattr(transaction, "account_id", None)
            notes = getattr(transaction, "notes", None)
            return await self.create_transaction(
                account_id=aid,
                transaction_type=ttype,
                amount=Decimal(str(amt)),
                description=notes,
            )
        except Exception:
            return None

    async def get_transactions_by_account_id(self, account_id: str | int) -> List[SavingsTransaction]:
        try:
            aid = int(str(account_id))
        except ValueError:
            return []
        result = await self.db.execute(
            select(SavingsTransaction)
            .where(SavingsTransaction.account_id == aid)
            .order_by(SavingsTransaction.created_at.desc())
            .limit(100)
        )
        return list(result.scalars().all())
