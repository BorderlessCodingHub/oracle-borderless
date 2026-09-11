"""lessons e lesson_chunks — base do mentor de aula (spec 2026-09-11 §4).

Revision ID: 0012_mentor_lessons
Revises: 0011_navigation_persistence
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0012_mentor_lessons"
down_revision = "0011_navigation_persistence"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536  # settings.EMBEDDING_DIM (snapshot na migration)


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("platform_video_id", sa.String(64), nullable=False),
        sa.Column("program_slug", sa.String(255), nullable=False),
        sa.Column("module_slug", sa.String(255), nullable=False),
        sa.Column("video_slug", sa.String(255), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_lessons_platform_video_id", "lessons", ["platform_video_id"], unique=True)
    op.create_index("ix_lessons_program_slug", "lessons", ["program_slug"])
    op.create_index("ix_lessons_transcript_status", "lessons", ["transcript_status"])

    op.create_table(
        "lesson_chunks",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.uuid", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_lesson_chunks_lesson_id", "lesson_chunks", ["lesson_id"])
    # HNSW por SQL cru: o Alembic não emite `USING hnsw` com opclass.
    op.execute(
        "CREATE INDEX ix_lesson_chunks_embedding_hnsw "
        "ON lesson_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_lesson_chunks_embedding_hnsw", table_name="lesson_chunks")
    op.drop_table("lesson_chunks")
    op.drop_table("lessons")
