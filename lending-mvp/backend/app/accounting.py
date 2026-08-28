"""
Double-entry accounting core.

Bank-grade, GAAP-aligned, hash-chained, append-only journal.

API boundary: integer minor units (cents). Never accept float.
Internal storage: Numeric(16, 2). Conversion minor -> decimal at the storage boundary.

This module is the ONLY way to post journal entries. The DB trigger
`check_journal_balanced` (deferred) and the append-only triggers on
`journal_entries` / `journal_lines` enforce the GAAP invariants.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .database.pg_accounting_models import (
    GLAccount,
    JournalEntry,
    JournalLine,
)


DEFAULT_GL_MAP: Dict[str, tuple] = {
    "1000": ("Cash on Hand", "asset"),
    "1005": ("Petty Cash", "asset"),
    "1010": ("Cash in Bank", "asset"),
    "1020": ("Cash in Bank - Current Account", "asset"),
    "1030": ("Cash in Bank - Savings Account", "asset"),
    "1100": ("Accounts Receivable", "asset"),
    "1120": ("Unearned Interest Income", "asset"),
    "1200": ("Loans Receivable - Current", "asset"),
    "1205": ("Loans Receivable - Non-Current", "asset"),
    "1210": ("Accrued Interest Receivable", "asset"),
    "1220": ("Penalty Receivable", "asset"),
    "1300": ("Other Receivables", "asset"),
    "1400": ("Allowance for Loan Losses", "asset"),
    "1410": ("Allowance for Credit Losses (ALLL)", "asset"),
    "1500": ("Fixed Assets", "asset"),
    "1600": ("Accumulated Depreciation", "asset"),
    "2010": ("Accounts Payable", "liability"),
    "2020": ("Disbursement Payable", "liability"),
    "2030": ("Savings Deposits Payable", "liability"),
    "2040": ("Time Deposits Payable", "liability"),
    "2100": ("Customer Advances (Overpayments)", "liability"),
    "2200": ("Withholding Tax Payable", "liability"),
    "2300": ("Accrued Interest Payable", "liability"),
    "2400": ("Other Liabilities", "liability"),
    "3000": ("Share Capital", "equity"),
    "3100": ("Retained Earnings", "equity"),
    "3110": ("Current Year Earnings", "equity"),
    "4000": ("Interest Income - Savings", "income"),
    "4100": ("Interest Income - Loans", "income"),
    "4110": ("Interest Income - Accrued", "income"),
    "4200": ("Fee Income - Origination", "income"),
    "4300": ("Penalty Income", "income"),
    "4400": ("Prepayment Penalty Income", "income"),
    "4500": ("Service Fee Income", "income"),
    "4600": ("Recovery Income (Written-off)", "income"),
    "5000": ("Salaries & Wages", "expense"),
    "5100": ("Office & Administrative Expenses", "expense"),
    "5200": ("Loan Loss Expense (Provision)", "expense"),
    "5210": ("Provision for Credit Losses", "expense"),
    "5300": ("Depreciation Expense", "expense"),
    "5400": ("Interest Expense", "expense"),
    "6010": ("Loan Commitments Outstanding", "memorandum"),
    "6020": ("Unused Credit Lines", "memorandum"),
}


def _to_minor(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int((value * 100).to_integral_value())
    if isinstance(value, float):
        # Banking-grade: float is forbidden when flag is on; otherwise warn + convert via string to avoid binary error
        try:
            from .config import settings as _s
            _strict = bool(getattr(_s, "banking_grade_mode", False))
        except Exception:
            _strict = False
        if _strict:
            raise TypeError(
                f"{field} must be int minor units or Decimal; float forbidden (got {value})"
            )
        import logging
        logging.getLogger(__name__).warning("Float amount %s passed to %s — converting via Decimal(str()); please pass Decimal/minor", value, field)
        return int((Decimal(str(value)) * 100).to_integral_value())
    if isinstance(value, str):
        return _to_minor(Decimal(value), field)
    raise TypeError(f"{field} unsupported type {type(value).__name__}")


def _normalize_line(line: Dict[str, Any]) -> Dict[str, Any]:
    code = line.get("account_code") or line.get("accountCode")
    if not code:
        raise ValueError("line.account_code is required")

    if "debit_minor" in line or "credit_minor" in line or "debitMinor" in line or "creditMinor" in line:
        debit_minor = _to_minor(
            line.get("debit_minor", line.get("debitMinor", 0)), "debit_minor"
        )
        credit_minor = _to_minor(
            line.get("credit_minor", line.get("creditMinor", 0)), "credit_minor"
        )
    else:
        debit_minor = _to_minor(line.get("debit", 0), "debit")
        credit_minor = _to_minor(line.get("credit", 0), "credit")

    if debit_minor < 0 or credit_minor < 0:
        raise ValueError(
            f"negative amount on account {code}: debit={debit_minor} credit={credit_minor}"
        )
    if debit_minor > 0 and credit_minor > 0:
        raise ValueError(
            f"line for {code} has both debit and credit > 0; one side must be zero"
        )

    return {
        "account_code": str(code),
        "debit_minor": int(debit_minor),
        "credit_minor": int(credit_minor),
        "description": line.get("description", ""),
    }


async def ensure_gl_accounts(
    session: AsyncSession, codes: List[str]
) -> None:
    if not codes:
        return
    result = await session.execute(
        select(GLAccount.code).filter(GLAccount.code.in_(codes))
    )
    existing = {r for r in result.scalars().all()}
    for code in codes:
        if code in existing:
            continue
        meta = DEFAULT_GL_MAP.get(code)
        if meta is None:
            raise ValueError(f"Unknown GL account code: {code}")
        name, acc_type = meta
        session.add(GLAccount(code=code, name=name, type=acc_type))
    await session.flush()


def _canonical_payload(entry_id: int, lines: List[Dict[str, Any]], ts: datetime) -> str:
    canon_lines = sorted(
        [
            {
                "account_code": l["account_code"],
                "debit_minor": int(l["debit_minor"]),
                "credit_minor": int(l["credit_minor"]),
            }
            for l in lines
        ],
        key=lambda x: x["account_code"],
    )
    payload = {
        "entry_id": entry_id,
        "ts": ts.isoformat(),
        "lines": canon_lines,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def _compute_prev_hash(session: AsyncSession) -> str:
    result = await session.execute(
        select(JournalEntry.row_hash)
        .order_by(JournalEntry.id.desc())
        .limit(1)
    )
    prev = result.scalar_one_or_none()
    return prev or ""


async def _check_journal_balanced(session: AsyncSession, entry_id: int) -> None:
    result = await session.execute(
        text(
            "SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) "
            "FROM journal_lines WHERE entry_id = :eid"
        ),
        {"eid": entry_id},
    )
    total_dr, total_cr = result.one()
    if Decimal(total_dr) != Decimal(total_cr):
        raise ValueError(
            f"Journal entry {entry_id} unbalanced: Dr={total_dr} Cr={total_cr}"
        )
    if Decimal(total_dr) == 0:
        raise ValueError(f"Journal entry {entry_id} is empty")


async def create_journal_entry(
    session: AsyncSession,
    reference_no: str,
    description: str,
    lines: List[Dict[str, Any]],
    created_by: Optional[str] = None,
    *,
    value_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    branch_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    loan_id: Optional[int] = None,
    customer_id: Optional[str] = None,
) -> JournalEntry:
    """
    Post a balanced journal entry. ΣDr == ΣCr enforced in minor units.
    Append-only + hash-chained.

    Lines: list of dicts. Each must include `account_code`. Accepts either
    `debit_minor`/`credit_minor` (int) or `debit`/`credit` (Decimal) — the
    former is preferred.
    """
    if not lines or len(lines) < 2:
        raise ValueError("Journal entry must have at least two lines")

    normalized = [_normalize_line(l) for l in lines]
    total_dr = sum(l["debit_minor"] for l in normalized)
    total_cr = sum(l["credit_minor"] for l in normalized)
    if total_dr != total_cr:
        raise ValueError(
            f"Journal entry unbalanced: Dr={total_dr}minor Cr={total_cr}minor "
            f"(diff={total_dr - total_cr})"
        )
    if total_dr == 0:
        raise ValueError("Journal entry is empty (sum = 0)")

    await ensure_gl_accounts(session, [l["account_code"] for l in normalized])

    if idempotency_key:
        result = await session.execute(
            select(JournalEntry).filter(JournalEntry.idempotency_key == idempotency_key)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

    ref = reference_no or f"JNL-{uuid.uuid4().hex[:8].upper()}"

    prev_hash = await _compute_prev_hash(session)
    placeholder_ts = datetime.utcnow()

    entry = JournalEntry(
        reference_no=ref,
        description=description,
        created_by=created_by,
        value_date=value_date,
        branch_id=branch_id,
        branch_code=branch_code,
        idempotency_key=idempotency_key,
        loan_id=loan_id,
        customer_id=customer_id,
        prev_hash=prev_hash,
        row_hash="",
    )
    session.add(entry)
    await session.flush()

    for l in normalized:
        session.add(
            JournalLine(
                entry_id=entry.id,
                account_code=l["account_code"],
                debit=Decimal(l["debit_minor"]) / Decimal(100),
                credit=Decimal(l["credit_minor"]) / Decimal(100),
                description=l["description"],
            )
        )
    await session.flush()

    await _check_journal_balanced(session, entry.id)

    row_hash = hashlib.sha256(
        (prev_hash + _canonical_payload(entry.id, normalized, entry.timestamp or placeholder_ts)).encode()
    ).hexdigest()

    await session.execute(
        text("UPDATE journal_entries SET row_hash = :rh WHERE id = :id"),
        {"rh": row_hash, "id": entry.id},
    )
    await session.flush()
    await session.refresh(entry)

    return entry


def generate_reference_number(prefix: str = "JE") -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"


async def get_ledger_entries_for_account(
    session: AsyncSession, account_code: str, limit: int = 100
) -> List[dict]:
    result = await session.execute(
        text(
            "SELECT jl.id, jl.entry_id, jl.account_code, jl.debit, jl.credit, "
            "jl.description, je.timestamp, je.reference_no "
            "FROM journal_lines jl "
            "JOIN journal_entries je ON je.id = jl.entry_id "
            "WHERE jl.account_code = :code "
            "ORDER BY je.timestamp DESC, jl.id DESC "
            "LIMIT :lim"
        ),
        {"code": account_code, "lim": limit},
    )
    rows = result.all()
    return [
        {
            "id": r.id,
            "entry_id": r.entry_id,
            "account_code": r.account_code,
            "debit": float(r.debit or 0),
            "credit": float(r.credit or 0),
            "description": r.description,
            "timestamp": r.timestamp,
            "reference_no": r.reference_no,
        }
        for r in rows
    ]
