"""Float to numeric for money columns

Revision ID: 2026_06_05_float_to_numeric
Revises: add_disbursement_001
Create Date: 2026-06-05

Convert:
  - aml_alerts.ctr_amount  (double precision → numeric(15,2))
  - collections.amount     (double precision → numeric(15,2))

Steps:
  1. Backfill NULL ctr_amount → 0.00 (required before casting to NOT-via-keep-NULL numeric
     in some PG versions and clearer for downstream joins/aggregates).
  2. ALTER COLUMN TYPE via USING expression (lossy cast is acceptable; reports
     only on actual money values that already fit numeric(15,2)).
  3. Drop any default of 0.0 on the column to avoid double-precision defaults
     leaking back in.

The migration is idempotent against re-runs by checking the column data_type
from information_schema before issuing the ALTER.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_06_05_float_to_numeric"
down_revision: Union[str, Sequence[str], None] = "add_disbursement_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_type(conn, table: str, column: str) -> str | None:
    res = conn.execute(
        sa.text(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).fetchone()
    return res[0] if res else None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. aml_alerts.ctr_amount ───────────────────────────────────────────
    if _column_type(conn, "aml_alerts", "ctr_amount") == "double precision":
        # Backfill NULLs first (the column is nullable=True, but rounding via
        # USING is cleaner once the NULL set is gone).
        conn.execute(
            sa.text("UPDATE aml_alerts SET ctr_amount = 0.0 WHERE ctr_amount IS NULL")
        )
        # Drop the default to avoid an implicit double-precision default
        conn.execute(sa.text("ALTER TABLE aml_alerts ALTER COLUMN ctr_amount DROP DEFAULT"))
        conn.execute(
            sa.text(
                "ALTER TABLE aml_alerts "
                "ALTER COLUMN ctr_amount TYPE numeric(15,2) "
                "USING ctr_amount::numeric(15,2)"
            )
        )

    # ── 2. collections.amount ──────────────────────────────────────────────
    if _column_type(conn, "collections", "amount") == "double precision":
        conn.execute(sa.text("ALTER TABLE collections ALTER COLUMN amount DROP DEFAULT"))
        conn.execute(
            sa.text(
                "ALTER TABLE collections "
                "ALTER COLUMN amount TYPE numeric(15,2) "
                "USING amount::numeric(15,2)"
            )
        )


def downgrade() -> None:
    """Reverse: convert numeric(15,2) back to double precision."""
    conn = op.get_bind()

    if _column_type(conn, "aml_alerts", "ctr_amount") == "numeric":
        conn.execute(
            sa.text(
                "ALTER TABLE aml_alerts "
                "ALTER COLUMN ctr_amount TYPE double precision "
                "USING ctr_amount::double precision"
            )
        )
        conn.execute(
            sa.text("ALTER TABLE aml_alerts ALTER COLUMN ctr_amount SET DEFAULT 0.0")
        )

    if _column_type(conn, "collections", "amount") == "numeric":
        conn.execute(
            sa.text(
                "ALTER TABLE collections "
                "ALTER COLUMN amount TYPE double precision "
                "USING amount::double precision"
            )
        )
        conn.execute(
            sa.text("ALTER TABLE collections ALTER COLUMN amount SET DEFAULT 0.0")
        )
