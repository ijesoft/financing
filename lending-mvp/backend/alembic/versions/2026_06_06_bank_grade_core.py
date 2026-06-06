"""Bank-grade GAAP core: idempotency, hash chain, append-only, NPL flag, indexes.

Revision ID: 2026_06_06_bank_grade_core
Revises: 2026_06_05_check_amount_nonneg
Create Date: 2026-06-06

Adds:
- transaction_idempotency table
- journal_entries: value_date, branch_id, branch_code, idempotency_key (UNIQUE),
  loan_id, customer_id, prev_hash, row_hash
- journal_lines: ON DELETE RESTRICT (preserve history)
- loan_applications: is_npl, non_accrual_since, collections_officer, ecl_stage
- append-only triggers on journal_entries / journal_lines
- deferred constraint trigger check_journal_balanced
- verify_journal_hash_chain() SQL function
- amortization_schedules: (loan_id, due_date) index, partial index on unpaid
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_06_06_bank_grade_core"
down_revision: Union[str, Sequence[str], None] = "2026_06_05_check_amount_nonneg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transaction_idempotency",
        sa.Column("idempotency_key", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("status_code", sa.BigInteger, nullable=False, server_default="200"),
        sa.Column("journal_entry_id", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_transaction_idempotency_expires", "transaction_idempotency", ["expires_at"])

    op.add_column("journal_entries", sa.Column("value_date", sa.Date(), nullable=True))
    op.add_column("journal_entries", sa.Column("branch_id", sa.BigInteger(), nullable=True))
    op.add_column("journal_entries", sa.Column("branch_code", sa.String(20), nullable=True))
    op.add_column("journal_entries", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column("journal_entries", sa.Column("loan_id", sa.BigInteger(), nullable=True))
    op.add_column("journal_entries", sa.Column("customer_id", sa.String(64), nullable=True))
    op.add_column("journal_entries", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("journal_entries", sa.Column("row_hash", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_journal_entries_idem", "journal_entries", ["idempotency_key"], unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_index("ix_journal_entries_loan", "journal_entries", ["loan_id"])
    op.create_index("ix_journal_entries_branch", "journal_entries", ["branch_code"])
    op.create_index("ix_journal_entries_value_date", "journal_entries", ["value_date"])

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_journal_lines_entry'
            ) THEN
                ALTER TABLE journal_lines
                    DROP CONSTRAINT IF EXISTS journal_lines_entry_id_fkey,
                    ADD CONSTRAINT journal_lines_entry_id_fkey
                    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE RESTRICT;
            END IF;
        END
        $$;
    """)

    op.add_column("loan_applications", sa.Column("is_npl", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("loan_applications", sa.Column("non_accrual_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("loan_applications", sa.Column("collections_officer", sa.String(64), nullable=True))
    op.add_column("loan_applications", sa.Column("ecl_stage", sa.String(10), nullable=True, server_default="S1"))
    op.create_index("ix_loan_applications_npl", "loan_applications", ["is_npl"], postgresql_where=sa.text("is_npl = true"))
    op.create_index("ix_loan_applications_branch_status", "loan_applications", ["branch_code", "status"])

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_amort_sched_loan_due
            ON amortization_schedules (loan_id, due_date);
        CREATE INDEX IF NOT EXISTS ix_amort_sched_unpaid
            ON amortization_schedules (loan_id, due_date)
            WHERE status IN ('pending', 'partial', 'overdue');
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION deny_journal_mutations()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND TG_TABLE_NAME = 'journal_entries'
               AND OLD.row_hash = ''
               AND NEW.row_hash <> ''
               AND NEW.reference_no = OLD.reference_no
               AND NEW.description IS NOT DISTINCT FROM OLD.description
               AND NEW.created_by IS NOT DISTINCT FROM OLD.created_by
               AND NEW.value_date IS NOT DISTINCT FROM OLD.value_date
               AND NEW.branch_id IS NOT DISTINCT FROM OLD.branch_id
               AND NEW.branch_code IS NOT DISTINCT FROM OLD.branch_code
               AND NEW.idempotency_key IS NOT DISTINCT FROM OLD.idempotency_key
               AND NEW.loan_id IS NOT DISTINCT FROM OLD.loan_id
               AND NEW.customer_id IS NOT DISTINCT FROM OLD.customer_id
               AND NEW.prev_hash IS NOT DISTINCT FROM OLD.prev_hash
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'journal_entries and journal_lines are append-only. Use compensating entries for corrections.';
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_journal_entries_no_update ON journal_entries;
        CREATE TRIGGER trg_journal_entries_no_update
            BEFORE UPDATE OR DELETE ON journal_entries
            FOR EACH ROW EXECUTE FUNCTION deny_journal_mutations();

        DROP TRIGGER IF EXISTS trg_journal_lines_no_update ON journal_lines;
        CREATE TRIGGER trg_journal_lines_no_update
            BEFORE UPDATE OR DELETE ON journal_lines
            FOR EACH ROW EXECUTE FUNCTION deny_journal_mutations();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION check_journal_balanced()
        RETURNS trigger AS $$
        DECLARE
            total_dr NUMERIC;
            total_cr NUMERIC;
        BEGIN
            SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0)
            INTO total_dr, total_cr
            FROM journal_lines
            WHERE entry_id = COALESCE(NEW.entry_id, OLD.entry_id);

            IF total_dr <> total_cr THEN
                RAISE EXCEPTION 'Journal entry % unbalanced: Dr=% Cr=%', COALESCE(NEW.entry_id, OLD.entry_id), total_dr, total_cr;
            END IF;
            IF total_dr = 0 THEN
                RAISE EXCEPTION 'Journal entry % is empty', COALESCE(NEW.entry_id, OLD.entry_id);
            END IF;
            RETURN NULL;
       ;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_journal_lines_balanced ON journal_lines;
        CREATE CONSTRAINT TRIGGER trg_journal_lines_balanced
            AFTER INSERT ON journal_lines
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION check_journal_balanced();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION verify_journal_hash_chain()
        RETURNS TABLE(entry_id BIGINT, valid BOOLEAN, computed_hash VARCHAR) AS $$
        DECLARE
            rec RECORD;
            prev VARCHAR(64) := '';
            expected VARCHAR(64);
            payload JSON;
        BEGIN
            FOR rec IN
                SELECT je.id, je.prev_hash, je.row_hash, je.timestamp,
                       COALESCE(json_agg(json_build_object(
                           'account_code', jl.account_code,
                           'debit_minor', (jl.debit * 100)::bigint,
                           'credit_minor', (jl.credit * 100)::bigint
                       ) ORDER BY jl.account_code), '[]'::json) AS lines_json
                FROM journal_entries je
                LEFT JOIN journal_lines jl ON jl.entry_id = je.id
                GROUP BY je.id, je.prev_hash, je.row_hash, je.timestamp
                ORDER BY je.id ASC
            LOOP
                payload := json_build_object(
                    'entry_id', rec.id,
                    'ts', rec.timestamp,
                    'lines', rec.lines_json
                );
                expected := encode(digest(prev || payload::text, 'sha256'), 'hex');
                entry_id := rec.id;
                computed_hash := expected;
                valid := (expected = rec.row_hash) AND (COALESCE(rec.prev_hash, '') = prev);
                RETURN NEXT;
                prev := rec.row_hash;
            END LOOP;
        ;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS verify_journal_hash_chain();")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_lines_balanced ON journal_lines;")
    op.execute("DROP FUNCTION IF EXISTS check_journal_balanced();")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_lines_no_update ON journal_lines;")
    op.execute("DROP TRIGGER IF EXISTS trg_journal_entries_no_update ON journal_entries;")
    op.execute("DROP FUNCTION IF EXISTS deny_journal_mutations();")

    op.drop_index("ix_loan_applications_branch_status", table_name="loan_applications")
    op.drop_index("ix_loan_applications_npl", table_name="loan_applications")
    op.drop_column("loan_applications", "ecl_stage")
    op.drop_column("loan_applications", "collections_officer")
    op.drop_column("loan_applications", "non_accrual_since")
    op.drop_column("loan_applications", "is_npl")

    op.drop_index("ix_journal_entries_value_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_branch", table_name="journal_entries")
    op.drop_index("ix_journal_entries_loan", table_name="journal_entries")
    op.drop_index("ix_journal_entries_idem", table_name="journal_entries")
    op.drop_column("journal_entries", "row_hash")
    op.drop_column("journal_entries", "prev_hash")
    op.drop_column("journal_entries", "customer_id")
    op.drop_column("journal_entries", "loan_id")
    op.drop_column("journal_entries", "idempotency_key")
    op.drop_column("journal_entries", "branch_code")
    op.drop_column("journal_entries", "branch_id")
    op.drop_column("journal_entries", "value_date")

    op.drop_index("ix_transaction_idempotency_expires", table_name="transaction_idempotency")
    op.drop_table("transaction_idempotency")
