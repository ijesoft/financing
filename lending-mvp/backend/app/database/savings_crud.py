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

    async def update_balance(self, account_id: int, amount: Decimal) -> bool:
        """Apply a signed delta to the balance. Returns True on success."""
        result = await self.db.execute(
            select(SavingsAccount).where(SavingsAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return False
        current = account.balance or Decimal("0.00")
        if not isinstance(current, Decimal):
            current = Decimal(str(current))
        delta = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        account.balance = current + delta
        await self.db.flush()
        return True
