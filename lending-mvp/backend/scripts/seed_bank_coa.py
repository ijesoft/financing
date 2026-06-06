"""
Idempotent CoA seeder. Safe to re-run. Adds any missing bank-grade accounts.

Usage (from project root):
    cd lending-mvp/backend
    python -m scripts.seed_bank_coa
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.accounting import DEFAULT_GL_MAP
from app.database import get_async_session_local
from app.database.pg_accounting_models import GLAccount


async def seed() -> int:
    factory = get_async_session_local()
    n = 0
    async with factory() as session:
        result = await session.execute(select(GLAccount.code))
        existing = {c for c in result.scalars().all()}
        for code, (name, acc_type) in DEFAULT_GL_MAP.items():
            if code in existing:
                continue
            session.add(GLAccount(code=code, name=name, type=acc_type))
            n += 1
        await session.commit()
    return n


if __name__ == "__main__":
    n = asyncio.run(seed())
    print(f"CoA seeder: inserted {n} new accounts (existing kept).")
