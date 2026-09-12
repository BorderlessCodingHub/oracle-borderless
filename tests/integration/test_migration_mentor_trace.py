"""I4: migração 0013 (colunas de mentor em `agent_traces`) espelhando
`test_migration_mentor_lessons.py`. ESCRITO MAS NÃO EXECUTADO (ruling B2): sem
Postgres disponível neste ambiente, validado só com `--collect-only`."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_agent_traces_mentor_columns_and_indexes_exist(db_session):
    columns = {
        row.column_name: row
        for row in (
            await db_session.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'agent_traces' "
                    "AND column_name IN "
                    "('lesson_id', 'program_slug', 'lesson_coverage', 'question_embedding')"
                )
            )
        ).all()
    }

    assert set(columns) == {
        "lesson_id", "program_slug", "lesson_coverage", "question_embedding",
    }

    # As quatro colunas do Task 5 (spec §9.1) são todas nullable — turno que
    # nunca passou pelo mentor não preenche nenhuma delas.
    assert columns["lesson_id"].is_nullable == "YES"
    assert columns["lesson_id"].data_type == "character varying"
    assert columns["program_slug"].is_nullable == "YES"
    assert columns["program_slug"].data_type == "character varying"
    assert columns["lesson_coverage"].is_nullable == "YES"
    assert columns["lesson_coverage"].data_type == "character varying"
    assert columns["question_embedding"].is_nullable == "YES"
    # pgvector expõe o tipo customizado "vector" no catalog do Postgres.
    assert columns["question_embedding"].data_type == "USER-DEFINED"

    for index in (
        "ix_agent_traces_lesson_id",
        "ix_agent_traces_program_slug",
        "ix_agent_traces_lesson_coverage",
    ):
        row = await db_session.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = :name"), {"name": index}
        )
        assert row.scalar_one() == 1, f"índice {index} não encontrado"

    # Sem índice ANN de propósito (ver comentário da migration): um HNSW sobre
    # coluna majoritariamente nula só custaria manutenção (spec §9.1).
    hnsw = await db_session.execute(
        text(
            "SELECT 1 FROM pg_indexes WHERE tablename = 'agent_traces' "
            "AND indexdef ILIKE '%hnsw%'"
        )
    )
    assert hnsw.first() is None
