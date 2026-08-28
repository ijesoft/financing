"""
PostgreSQL-only savings CRUD.

Replaces the previous Mongo/Postgres dual-store implementation. All writes go
directly to the `savings_accounts` table via SQLAlchemy AsyncSession.
"""

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .pg_core_models import SavingsAccount


class SavingsCRUD:
    """CRUD for savings_accounts (PostgreSQL only)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_savings_account(self, account: SavingsAccount) -> SavingsAccount:
        """Persist a SavingsAccount ORM instance."""
        self.db.add(account)
        await self.db.flush()
        await self.db.refresh(account)
        return account

    async def get_savings_account_by_id(self, account_id: int) -> Optional[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_savings_account_by_number(self, account_number: str) -> Optional[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.account_number == account_number)
        )
        return result.scalar_one_or_none()

    async def get_savings_accounts_by_customer(
        self, customer_id: int, skip: int = 0, limit: int = 100
    ) -> List[SavingsAccount]:
        result = await self.db.execute(
            select(SavingsAccount)
            .where(SavingsAccount.customer_id == customer_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_all_savings_accounts(
        self,
        search_term: Optional[str] = None,
        customer_id: Optional[str] = None,
        branch: Optional[str] = None,
        status: Optional[str] = None,
        account_type: Optional[str] = None,
    ) -> List[SavingsAccount]:
        """PG-only: fetch all savings accounts with optional filters (replaces Mongo dual-store)."""
        from sqlalchemy import and_
        from .pg_core_models import Customer
        from .pg_models import Branch  # noqa: F401 — ensures branch table exists for joins if needed

        stmt = select(SavingsAccount)
        # Join customer for branch filter if needed
        if branch:
            stmt = stmt.join(Customer, Customer.id == SavingsAccount.customer_id).where(Customer.branch_code == branch)
        if customer_id is not None:
            try:
                cid = int(str(customer_id))
                stmt = stmt.where(SavingsAccount.customer_id == cid)
            except ValueError:
                # invalid customer_id → empty
                return []
        if search_term:
            stmt = stmt.where(SavingsAccount.account_number.ilike(f"%{search_term}%"))
        if status:
            stmt = stmt.where(SavingsAccount.status == status)
        if account_type:
            stmt = stmt.where(SavingsAccount.account_type == account_type)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_balance(self, account_id: int, amount: Decimal, for_update: bool = True) -> bool:
        """Apply a signed delta to the balance. Returns True on success.

        Banking-grade: uses SELECT FOR UPDATE to prevent race conditions on concurrent deposits/withdrawals.
        """
        # Coerce account_id to int if passed as string (legacy callers)
        try:
            aid = int(str(account_id))
        except ValueError:
            return False
        stmt = select(SavingsAccount).where(SavingsAccount.id == aid)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        account = result.scalar_one_or_none()
        if not account:
            return False
        current = account.balance or Decimal("0.00")
        if not isinstance(current, Decimal):
            current = Decimal(str(current))
        delta = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        new_balance = current + delta
        # Enforce non-negative balance at app layer (DB CHECK also enforces)
        if new_balance < Decimal("0.00"):
            return False
        account.balance = new_balance
        await self.db.flush()
        return True
