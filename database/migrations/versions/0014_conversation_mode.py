"""Coluna `mode` em `conversations` (spec 2026-10-05 §5.1).

A coluna de chats da Platform lista só `mode='chat'`; consultas da barra ⌘K
(`navigate`) e do Mentor (`mentor`) continuam gravadas, mas fora da lista.

Backfill das linhas antigas pelos intents de `agent_traces`: `conversations`
nunca gravou de onde a conversa veio, mas cada turno grava um trace com o
`intent` classificado, então os traces são a única fonte confiável. Regra:
- traces existem e são TODOS `intent = 'navigate'` → `mode = 'navigate'`;
- traces existem e são TODOS `intent = 'mentor'` → `mode = 'mentor'`;
- o resto (intents mistos, knowledge, chit-chat ou sem traces) → `mode = 'chat'`.
Jogar tudo em 'chat' poluiria a lista de chats com threads da ⌘K e do Mentor.
Limitação conhecida: no modo chat o gate também pode rotular um turno como
`intent='navigate'`, então uma thread do painel de chat em que todo turno saiu
como navigate vira `navigate`; aceito porque a regra só roda sobre dados
locais legados (o Oracle nunca teve deploy).

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


def _single_intent_backfill(mode: str) -> str:
    return (
        f"UPDATE conversations c SET mode = '{mode}' "
        "WHERE c.mode IS NULL "
        "AND EXISTS (SELECT 1 FROM agent_traces t WHERE t.conversation_id = c.uuid) "
        "AND NOT EXISTS (SELECT 1 FROM agent_traces t WHERE t.conversation_id = c.uuid "
        f"AND t.intent IS DISTINCT FROM '{mode}')"
    )


# Ordem importa: cada UPDATE só toca `mode IS NULL`, então o 'chat' final pega
# apenas o que não foi classificado como navigate/mentor.
BACKFILL_STATEMENTS: tuple[str, ...] = (
    _single_intent_backfill("navigate"),
    _single_intent_backfill("mentor"),
    "UPDATE conversations SET mode = 'chat' WHERE mode IS NULL",
)


def upgrade() -> None:
    op.add_column("conversations", sa.Column("mode", sa.String(16), nullable=True))
    for statement in BACKFILL_STATEMENTS:
        op.execute(statement)
    op.create_index(
        "ix_conversations_user_email_mode", "conversations", ["user_email", "mode"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_email_mode", table_name="conversations")
    op.drop_column("conversations", "mode")
