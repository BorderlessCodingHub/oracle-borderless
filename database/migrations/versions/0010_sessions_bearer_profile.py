"""sessions — origem da sessão (cookie do oráculo ou bearer da plataforma) e
snapshot do perfil (membership, seniority, careerStage) usado no prompt de
navegação sem ir à rede a cada turno.

Revision ID: 0010_sessions_bearer_profile
Revises: 0009_sessions
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_sessions_bearer_profile"
down_revision = "0009_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("source", sa.String(32), nullable=False, server_default="oracle_login"))
    op.add_column("sessions", sa.Column("user_membership", sa.String(16), nullable=True))
    op.add_column("sessions", sa.Column("user_seniority", sa.String(16), nullable=True))
    op.add_column("sessions", sa.Column("user_career_stage", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "user_career_stage")
    op.drop_column("sessions", "user_seniority")
    op.drop_column("sessions", "user_membership")
    op.drop_column("sessions", "source")
