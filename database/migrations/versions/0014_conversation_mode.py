"""Coluna `mode` em `conversations` (spec 2026-10-05 §5.1).

A coluna de chats da Platform lista só `mode='chat'`; consultas da barra ⌘K
(`navigate`) e do Mentor (`mentor`) continuam gravadas, mas fora da lista.
Backfill para 'chat': o Oracle ainda não tem deploy, só bancos locais têm
linhas antigas.

Revision ID: 0014_conversation_mode
Revises: 0013_mentor_trace
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_conversation_mode"
down_revision = "0013_mentor_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("mode", sa.String(16), nullable=True))
    op.execute("UPDATE conversations SET mode = 'chat' WHERE mode IS NULL")
    op.create_index(
        "ix_conversations_user_email_mode", "conversations", ["user_email", "mode"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_email_mode", table_name="conversations")
    op.drop_column("conversations", "mode")
