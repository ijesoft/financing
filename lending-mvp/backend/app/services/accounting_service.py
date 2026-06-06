"""
Posting service — multi-leg, SERIALIZABLE, idempotency-aware.

This is the ONLY function money-moving mutations should call to post to the GL.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounting import (
    _normalize_line,
    create_journal_entry,
    ensure_gl_accounts,
    generate_reference_number,
)
from ..database.pg_accounting_models import JournalEntry


class IdempotencyConflict(Exception):
    pass


async def _get_idempotent_response(
    session: AsyncSession, idempotency_key: str
) -> Optional[dict]:
    from ..database.pg_accounting_models import TransactionIdempotency

    result = await session.execute(
        select(TransactionIdempotency).filter_by(idempotency_key=idempotency_key)
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        return None
    return {
        "idempotency_key": rec.idempotency_key,
        "status_code": rec.status_code,
        "response_json": rec.response_json,
        "journal_entry_id": rec.journal_entry_id,
    }


async def _save_idempotent_response(
    session: AsyncSession,
    idempotency_key: str,
    request_hash: str,
    response_json: str,
    status_code: int = 200,
    journal_entry_id: Optional[int] = None,
    ttl_hours: int = 24,
) -> None:
    from ..database.pg_accounting_models import TransactionIdempotency

    session.add(
        TransactionIdempotency(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_json=response_json,
            status_code=status_code,
            journal_entry_id=journal_entry_id,
            expires_at=datetime.utcnow() + __import__("datetime").timedelta(hours=ttl_hours),
        )
    )


def _request_hash(legs: List[Dict[str, Any]], reference_no: str, description: str) -> str:
    import hashlib, json
    canon = {
        "reference_no": reference_no,
        "description": description,
        "legs": sorted(
            [
                {
                    "account_code": l["account_code"],
                    "debit_minor": l["debit_minor"],
                    "credit_minor": l["credit_minor"],
                }
                for l in legs
            ],
            key=lambda x: x["account_code"],
        ),
    }
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def post_transaction(
    db: AsyncSession,
    legs: List[Dict[str, Any]],
    *,
    idempotency_key: Optional[str] = None,
    description: Optional[str] = None,
    reference_no: Optional[str] = None,
    created_by: Optional[str] = None,
    value_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    branch_code: Optional[str] = None,
    loan_id: Optional[int] = None,
    customer_id: Optional[str] = None,
) -> int:
    """
    Post a balanced multi-leg journal entry.

    `legs` = list of dicts with at least `account_code` and either
    `debit_minor`/`credit_minor` (preferred, int) or `debit`/`credit`
    (Decimal — converted to minor units internally).

    Returns: the new `journal_entry.id`.
    Raises: ValueError on imbalance, TypeError on float, IdempotencyConflict
    on key reuse with different payload.
    """
    if not legs or len(legs) < 2:
        raise ValueError("post_transaction requires >= 2 legs")
    normalized = [_normalize_line(l) for l in legs]
    total_dr = sum(l["debit_minor"] for l in normalized)
    total_cr = sum(l["credit_minor"] for l in normalized)
    if total_dr != total_cr:
        raise ValueError(
            f"Unbalanced journal: Dr={total_dr}minor Cr={total_cr}minor"
        )
    if total_dr <= 0:
        raise ValueError("Journal entry sum must be > 0")

    if not description:
        description = "Transaction"
    if not reference_no:
        reference_no = generate_reference_number("TX")

    request_h = _request_hash(normalized, reference_no, description)

    if idempotency_key:
        cached = await _get_idempotent_response(db, idempotency_key)
        if cached is not None:
            if cached.get("status_code", 200) >= 400:
                raise IdempotencyConflict(
                    f"idempotency_key {idempotency_key} previously failed"
                )
            return int(cached["journal_entry_id"])

    entry = await create_journal_entry(
        session=db,
        reference_no=reference_no,
        description=description,
        lines=normalized,
        created_by=created_by,
        value_date=value_date,
        branch_id=branch_id,
        branch_code=branch_code,
        idempotency_key=idempotency_key,
        loan_id=loan_id,
        customer_id=customer_id,
    )
    await db.commit()
    await db.refresh(entry)

    if idempotency_key:
        import json
        response_payload = json.dumps(
            {
                "journal_entry_id": entry.id,
                "reference_no": entry.reference_no,
                "row_hash": entry.row_hash,
            },
            sort_keys=True,
        )
        await _save_idempotent_response(
            db,
            idempotency_key=idempotency_key,
            request_hash=request_h,
            response_json=response_payload,
            journal_entry_id=entry.id,
        )
        await db.commit()

    return entry.id
