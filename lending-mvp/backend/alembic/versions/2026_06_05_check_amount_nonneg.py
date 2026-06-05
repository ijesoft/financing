"""CHECK (amount >= 0) on money columns

Revision ID: 2026_06_05_check_amount_nonneg
Revises: 2026_06_05_float_to_numeric
Create Date: 2026-06-05

Add CHECK (col >= 0) to every money column on every money table.
A negative value is illegal on these columns by banking convention.

NOTE: This migration only adds CHECKs to tables that exist at migration
time. Tables created later by `Base.metadata.create_all` (e.g.
`savings_accounts`, `aml_alerts`) are added to a follow-up migration
that runs after the application starts. See test_check_amount_nonneg.py
for the test-side reapplication that mirrors the production flow.

Idempotent: re-runs are no-ops because each CHECK is gated on the
absence of a same-named constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_06_05_check_amount_nonneg"
down_revision: Union[str, Sequence[str], None] = "2026_06_05_float_to_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) pairs that must have CHECK (col >= 0).
MONEY_COLUMNS = [
    ("loan_applications", "principal"),
    ("loan_applications", "approved_principal"),
    ("loan_applications", "outstanding_balance"),
    ("loan_transactions", "amount"),
    ("savings_accounts", "balance"),
    ("savings_accounts", "principal"),
    ("savings_accounts", "target_amount"),
    ("savings_transactions", "amount"),
    ("savings_transactions", "balance_before"),
    ("savings_transactions", "balance_after"),
    ("collections", "amount"),
    ("aml_alerts", "ctr_amount"),
    ("journal_lines", "debit"),
    ("journal_lines", "credit"),
    ("amortization_schedules", "principal_due"),
    ("amortization_schedules", "interest_due"),
    ("amortization_schedules", "penalty_due"),
    ("amortization_schedules", "principal_paid"),
    ("amortization_schedules", "interest_paid"),
    ("amortization_schedules", "penalty_paid"),
]


def _add_check(conn, table: str, column: str) -> None:
    """Add CHECK (col >= 0) to a column if not already present."""
    name = f"ck_{table}_{column}_nonneg"
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    ).fetchone()
    if exists:
        return
    conn.execute(
        sa.text(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" '
            f'CHECK ("{column}" >= 0)'
        )
    )


def _drop_check(conn, table: str, column: str) -> None:
    name = f"ck_{table}_{column}_nonneg"
    conn.execute(
        sa.text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
    )


def upgrade() -> None:
    conn = op.get_bind()
    for table, column in MONEY_COLUMNS:
        # Only attempt to add on tables that exist (some are in Base.metadata
        # but not in migrations and may be absent in pure-migration runs).
        table_exists = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
            ),
            {"t": table},
        ).fetchone()
        if not table_exists:
            continue
        col_exists = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).fetchone()
        if not col_exists:
            continue
        _add_check(conn, table, column)


def downgrade() -> None:
    conn = op.get_bind()
    for table, column in MONEY_COLUMNS:
        _drop_check(conn, table, column)
