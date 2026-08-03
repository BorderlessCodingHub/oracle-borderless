"""agent_traces — trace por turno do oráculo (ADR-0013)

Revision ID: 0006_agent_traces
Revises: 0005_support_tracking_tables
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_agent_traces"
down_revision = "0005_support_tracking_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_traces",
        sa.Column("uuid", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.uuid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.uuid", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_email", sa.String(length=320), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("history_messages", sa.Integer(), nullable=False),
        sa.Column("history_tokens_est", sa.Integer(), nullable=False),
        sa.Column("gate_retrieve", sa.Boolean(), nullable=False),
        sa.Column("gate_search_query", sa.String(length=512), nullable=True),
        sa.Column("gate_degraded", sa.Boolean(), nullable=False),
        sa.Column("gate_ms", sa.Integer(), nullable=False),
        sa.Column("retrieval_ran", sa.Boolean(), nullable=False),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False),
        sa.Column("retrieval_kept", sa.Integer(), nullable=False),
        sa.Column("retrieval_best_distance", sa.Float(), nullable=True),
        sa.Column("retrieval_threshold", sa.Float(), nullable=False),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("engine_ms", sa.Integer(), nullable=True),
        sa.Column("citations_count", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_traces_conversation_id", "agent_traces", ["conversation_id"])
    op.create_index("ix_agent_traces_gate_retrieve", "agent_traces", ["gate_retrieve"])
    op.create_index("ix_agent_traces_outcome", "agent_traces", ["outcome"])
    op.create_index("ix_agent_traces_created_at", "agent_traces", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_traces_created_at", table_name="agent_traces")
    op.drop_index("ix_agent_traces_outcome", table_name="agent_traces")
    op.drop_index("ix_agent_traces_gate_retrieve", table_name="agent_traces")
    op.drop_index("ix_agent_traces_conversation_id", table_name="agent_traces")
    op.drop_table("agent_traces")
