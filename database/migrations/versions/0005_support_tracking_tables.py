"""job_executions + seeds_executions (tracking transversal do support)

Fecha um débito que vinha do M1: os models `JobExecution` e `SeedExecution`
existem em `BaseModel.metadata` desde o início, mas nunca ganharam migration.
Sem estas tabelas, `Job.execute()` (idempotência do scheduler) e o tracking de
seeds falham em runtime, e `alembic check` acusava as duas como "added table"
em todo autogenerate.

Revision ID: 0005_support_tracking_tables
Revises: 0004_documents_kb_provenance
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_support_tracking_tables"
down_revision = "0004_documents_kb_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_executions",
        sa.Column("uuid", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=2048), nullable=True),
    )
    op.create_index("ix_job_executions_job_name", "job_executions", ["job_name"])

    op.create_table(
        "seeds_executions",
        sa.Column("uuid", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("seed_name", sa.String(length=255), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_seeds_executions_seed_name", "seeds_executions", ["seed_name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_seeds_executions_seed_name", table_name="seeds_executions")
    op.drop_table("seeds_executions")
    op.drop_index("ix_job_executions_job_name", table_name="job_executions")
    op.drop_table("job_executions")
