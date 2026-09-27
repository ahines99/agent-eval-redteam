"""Persist ownership of running workflows.

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_leases",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.run_id"), primary_key=True),
        sa.Column("owner", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("execution_leases")
