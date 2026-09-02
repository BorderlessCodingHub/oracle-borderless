"""agent_traces: events sai, langsmith_run_id entra

A sequência passo-a-passo do turno é o que o LangSmith já faz melhor do que o
Postgres — o trace agora guarda só a referência ao run (ver spec, seção 3).

O `drop_column` descarta os eventos históricos — é intencional e irreversível.
Se houver dados em produção que valham a pena, exporte antes de rodar.

Revision ID: 0007_agent_traces_langsmith
Revises: 0006_agent_traces
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_agent_traces_langsmith"
down_revision = "0006_agent_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_traces", sa.Column("langsmith_run_id", sa.String(length=64), nullable=True))
    op.drop_column("agent_traces", "events")


def downgrade() -> None:
    op.add_column(
        "agent_traces",
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_column("agent_traces", "langsmith_run_id")
