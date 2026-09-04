"""sessions — sessão do oráculo: hash do cookie + accessToken da plataforma (ADR-0018).

Revision ID: 0009_sessions
Revises: 0008_rate_limits
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_sessions"
down_revision = "0008_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("platform_access_token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("user_email", sa.String(320), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("user_username", sa.String(255), nullable=True),
        sa.Column("last_platform_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_email", "sessions", ["user_email"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_email", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
