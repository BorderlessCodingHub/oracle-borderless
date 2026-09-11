"""messages.navigation e colunas de navegação no agent_traces (spec §5.5).

Revision ID: 0011_navigation_persistence
Revises: 0010_sessions_bearer_profile
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_navigation_persistence"
down_revision = "0010_sessions_bearer_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("navigation", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_traces", sa.Column("intent", sa.String(16), nullable=True))
    op.add_column("agent_traces", sa.Column("navigation_called", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("agent_traces", sa.Column("navigation_access", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_traces", "navigation_access")
    op.drop_column("agent_traces", "navigation_called")
    op.drop_column("agent_traces", "intent")
    op.drop_column("messages", "navigation")
