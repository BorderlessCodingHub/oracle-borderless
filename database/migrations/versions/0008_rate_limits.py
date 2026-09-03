"""rate_limits — contador de janela fixa para rate limit (ADR-0017).

Revision ID: 0008_rate_limits
Revises: 0007_agent_traces_langsmith
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_rate_limits"
down_revision = "0007_agent_traces_langsmith"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
