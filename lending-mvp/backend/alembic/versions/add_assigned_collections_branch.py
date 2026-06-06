"""add assigned_collections_branch to loan_applications

Revision ID: add_assigned_collections_branch
Revises: 2026_06_06_bank_grade_core
Create Date: 2026-06-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_assigned_collections_branch'
down_revision: Union[str, None] = '2026_06_06_bank_grade_core'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "loan_applications",
        sa.Column("assigned_collections_branch", sa.String(20), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_index("ix_loan_applications_assigned_collections_branch", table_name="loan_applications")
    op.drop_column("loan_applications", "assigned_collections_branch")
