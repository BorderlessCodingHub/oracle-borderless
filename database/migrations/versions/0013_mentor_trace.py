"""Colunas de mentor no agent_traces (spec 2026-09-11 §9.1).

Revision ID: 0013_mentor_trace
Revises: 0012_mentor_lessons
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0013_mentor_trace"
down_revision = "0012_mentor_lessons"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536  # settings.EMBEDDING_DIM (snapshot na migration)


def upgrade() -> None:
    op.add_column("agent_traces", sa.Column("lesson_id", sa.String(64), nullable=True))
    op.add_column("agent_traces", sa.Column("program_slug", sa.String(255), nullable=True))
    op.add_column("agent_traces", sa.Column("lesson_coverage", sa.String(16), nullable=True))
    # Sem índice ANN de propósito: agrupar alguns milhares de perguntas é
    # varredura, e um HNSW sobre coluna majoritariamente nula só custaria
    # manutenção (spec §9.1).
    op.add_column("agent_traces", sa.Column("question_embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.create_index("ix_agent_traces_lesson_id", "agent_traces", ["lesson_id"])
    op.create_index("ix_agent_traces_program_slug", "agent_traces", ["program_slug"])
    op.create_index("ix_agent_traces_lesson_coverage", "agent_traces", ["lesson_coverage"])


def downgrade() -> None:
    op.drop_index("ix_agent_traces_lesson_coverage", table_name="agent_traces")
    op.drop_index("ix_agent_traces_program_slug", table_name="agent_traces")
    op.drop_index("ix_agent_traces_lesson_id", table_name="agent_traces")
    op.drop_column("agent_traces", "question_embedding")
    op.drop_column("agent_traces", "lesson_coverage")
    op.drop_column("agent_traces", "program_slug")
    op.drop_column("agent_traces", "lesson_id")
