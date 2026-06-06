"""
Smoke test: post a balanced journal entry, verify ΣDr == ΣCr.

Usage:
    cd lending-mvp/backend
    python -m scripts.smoke_test_je
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app.database import get_async_session_local
from app.services.accounting_service import post_transaction


async def smoke_test() -> None:
    factory = get_async_session_local()
    async with factory() as session:
        je_id = await post_transaction(
            session,
            legs=[
                {"account_code": "1200", "debit_minor": 100000, "credit_minor": 0},
                {"account_code": "1010", "debit_minor": 0, "credit_minor": 100000},
            ],
            description="Smoke test: balanced 1000.00 debit/credit",
            idempotency_key="SMOKE-001",
        )
        await session.commit()
        result = await session.execute(
            text(
                "SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) "
                "FROM journal_lines WHERE entry_id = :id"
            ),
            {"id": je_id},
        )
        dr, cr = result.one()
        assert Decimal(dr) == Decimal(cr), f"FAIL: Dr={dr} != Cr={cr}"
        print(f"PASS: journal entry {je_id} balanced (Dr={dr} Cr={cr})")

        bad_id = None
        try:
            bad_id = await post_transaction(
                session,
                legs=[
                    {"account_code": "1200", "debit_minor": 100000, "credit_minor": 0},
                    {"account_code": "1010", "debit_minor": 0, "credit_minor": 99999},
                ],
                description="intentional imbalance",
                idempotency_key="SMOKE-002",
            )
            print(f"FAIL: imbalanced entry was accepted (id={bad_id})")
        except ValueError as e:
            print(f"PASS: imbalanced entry rejected — {e}")


if __name__ == "__main__":
    asyncio.run(smoke_test())
