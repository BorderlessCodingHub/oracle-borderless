"""documents.kb_root_page_id + kb_section (procedência de escopo — ADR-0012)

Revision ID: 0004_documents_kb_provenance
Revises: 0003_documents_last_edited_time
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_documents_kb_provenance"
down_revision = "0003_documents_last_edited_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("kb_root_page_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("kb_section", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_documents_kb_root_page_id", "documents", ["kb_root_page_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_kb_root_page_id", table_name="documents")
    op.drop_column("documents", "kb_section")
    op.drop_column("documents", "kb_root_page_id")
