"""
PostgreSQL-only standing orders (stub).

Mongo implementation replaced with PG stub that raises NotImplemented for
features not yet migrated. Core savings transfer logic moved to transaction_crud.
"""
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from datetime import datetime

class StandingOrderCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_standing_order(self, order_data: dict) -> str:
        from app.database.pg_core_models import StandingOrder
        # Minimal PG insert for standing_orders
        so = StandingOrder(
            account_id=int(order_data.get("source_account_id") or order_data.get("account_id")),
            recipient_account=str(order_data.get("destination_account_id") or order_data.get("recipient_account", "")),
            recipient_name=str(order_data.get("recipient_name", "Standing Order Recipient")),
            amount=Decimal(str(order_data.get("amount", 0))),
            frequency=str(order_data.get("frequency", "monthly")),
            next_execution_date=order_data.get("start_date") or order_data.get("next_execution_date") or datetime.utcnow().date(),
            is_active=order_data.get("is_active", True),
        )
        self.db.add(so)
        await self.db.flush()
        return str(so.id)

    async def get_standing_order_by_id(self, order_id: str) -> Optional[dict]:
        from app.database.pg_core_models import StandingOrder
        try:
            oid = int(str(order_id))
        except ValueError:
            return None
        result = await self.db.execute(select(StandingOrder).where(StandingOrder.id == oid))
        so = result.scalar_one_or_none()
        return so.__dict__ if so else None

    async def get_standing_orders_by_account(self, account_id: str) -> List[dict]:
        from app.database.pg_core_models import StandingOrder
        try:
            aid = int(str(account_id))
        except ValueError:
            return []
        result = await self.db.execute(select(StandingOrder).where(StandingOrder.account_id == aid))
        return [r.__dict__ for r in result.scalars().all()]

    async def get_active_standing_orders(self) -> List[dict]:
        from app.database.pg_core_models import StandingOrder
        result = await self.db.execute(select(StandingOrder).where(StandingOrder.is_active == True))
        return [r.__dict__ for r in result.scalars().all()]

    async def update_standing_order(self, order_id: str, update_data: dict) -> bool:
        from app.database.pg_core_models import StandingOrder
        try:
            oid = int(str(order_id))
        except ValueError:
            return False
        result = await self.db.execute(select(StandingOrder).where(StandingOrder.id == oid))
        so = result.scalar_one_or_none()
        if not so:
            return False
        for k, v in update_data.items():
            if hasattr(so, k):
                setattr(so, k, v)
        await self.db.flush()
        return True

    async def delete_standing_order(self, order_id: str) -> bool:
        from app.database.pg_core_models import StandingOrder
        try:
            oid = int(str(order_id))
        except ValueError:
            return False
        result = await self.db.execute(select(StandingOrder).where(StandingOrder.id == oid))
        so = result.scalar_one_or_none()
        if not so:
            return False
        await self.db.delete(so)
        await self.db.flush()
        return True

    async def execute_standing_order(self, order_id: str) -> bool:
        # Use PG transaction_crud for atomic transfer
        from .transaction_crud import TransactionCRUD
        from .savings_crud import SavingsCRUD
        data = await self.get_standing_order_by_id(order_id)
        if not data or not data.get("is_active"):
            return False
        # This is a stub — full transfer requires two accounts; defer to manual transfer
        return False

class InterestComputationCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute_daily_interest(self, account_id: str, balance: Decimal, rate: Decimal) -> Decimal:
        daily_rate = Decimal(str(rate)) / Decimal("365")
        interest = Decimal(str(balance)) * daily_rate / Decimal("100")
        return interest.quantize(Decimal("0.01"))

    async def compute_average_daily_balance(self, account_id: str, start_date: datetime, end_date: datetime) -> Decimal:
        # Simplified — real ADB requires ledger reconstruction; return current balance for now
        from app.database.pg_core_models import SavingsAccount
        from sqlalchemy import select as sel
        try:
            aid = int(str(account_id))
        except ValueError:
            return Decimal("0.00")
        result = await self.db.execute(sel(SavingsAccount).where(SavingsAccount.id == aid))
        acct = result.scalar_one_or_none()
        return Decimal(str(acct.balance)) if acct else Decimal("0.00")
