"""Testes unitários dos repositórios de aula com uma sessão fake — sem banco.

Cobrem o que dá para verificar sem PostgreSQL: o SQL que `list_pending` monta,
que `upsert_from_catalog` não pisa no estado de transcrição de um model já
existente, e que `replace_for_lesson` manda o DELETE antes dos inserts. A
cobertura de ponta a ponta (constraints, pgvector, HNSW) fica para
`tests/integration/domain/lessons/test_lesson_repository.py`.
"""

from uuid import uuid4

import pytest

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.models.lesson import LessonModel
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.exceptions import NotFoundError


class _Scalars:
    """Mimetiza o pedaço de `Result` usado por `.scalars().all()`."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class FakeResult:
    """Mimetiza só o que os repositórios chamam num `Result` do SQLAlchemy."""

    def __init__(self, *, scalar=None, rows: list | None = None) -> None:
        self._scalar = scalar
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def all(self) -> list:
        return self._rows


class FakeSession:
    """Sessão fake: grava o que recebeu, sem tocar em banco nenhum.

    `execute_results` é consumida em ordem — cada chamada a `execute()` some
    o próximo resultado da fila (ou devolve um `FakeResult()` vazio se a fila
    acabou).
    """

    def __init__(self, execute_results: list[FakeResult] | None = None) -> None:
        self.executed_statements: list = []
        self.added: list = []
        self.flush_calls = 0
        self.refreshed: list = []
        self._execute_results = list(execute_results or [])

    async def execute(self, stmt):
        self.executed_statements.append(stmt)
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    def add(self, model) -> None:
        self.added.append(model)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def refresh(self, model) -> None:
        self.refreshed.append(model)


@pytest.fixture
def fake_session():
    session = FakeSession()
    CurrentAsyncSessionContext.set(session)
    try:
        yield session
    finally:
        CurrentAsyncSessionContext.clear()


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_list_pending_filters_by_status_attempts_and_program(fake_session):
    repo = LessonRepository()

    await repo.list_pending("base", max_attempts=3)

    assert len(fake_session.executed_statements) == 1
    sql = _compiled(fake_session.executed_statements[0])
    assert "transcript_status IN ('pending', 'failed')" in sql
    assert "attempts < 3" in sql
    assert "program_slug = 'base'" in sql
    # Desempate determinístico: aulas sincronizadas na mesma transação
    # compartilham `created_at`, então `--limit N` precisa de mais critério.
    assert "ORDER BY lessons.created_at, lessons.module_slug, lessons.video_slug" in sql


@pytest.mark.asyncio
async def test_list_pending_also_recovers_stale_transcribing_claims(fake_session):
    repo = LessonRepository()

    await repo.list_pending("base", max_attempts=3)

    assert len(fake_session.executed_statements) == 1
    sql = _compiled(fake_session.executed_statements[0])
    # claim obsoleto (transcribing há mais tempo que MENTOR_CLAIM_STALE_MINUTES) volta ao lote
    assert "transcript_status = 'transcribing'" in sql
    assert "updated_at <" in sql
    # e o ramo pending/failed original continua lá, com o mesmo teto de tentativas
    assert "transcript_status IN ('pending', 'failed')" in sql
    assert "attempts < 3" in sql


@pytest.mark.asyncio
async def test_upsert_from_catalog_updates_only_catalog_fields_on_existing_model():
    existing = LessonModel(
        uuid=uuid4(),
        platform_video_id="v1",
        program_slug="base",
        module_slug="modulo-1",
        video_slug="aula-1",
        title="Tokens",
        duration_seconds=100,
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
        transcript_text="conteúdo já transcrito",
        transcript_status="ready",
        content_hash="h",
        attempts=0,
        failure_reason=None,
    )
    session = FakeSession(execute_results=[FakeResult(scalar=existing)])
    CurrentAsyncSessionContext.set(session)
    try:
        repo = LessonRepository()
        incoming = Lesson(
            uuid=uuid4(),
            platform_video_id="v1",
            program_slug="base",
            module_slug="modulo-1",
            video_slug="aula-1",
            title="Tokens (revisado)",
            provider="PANDA_VIDEO",
            provider_ref="ref-1",
            transcript_status=TranscriptStatus.PENDING,
        )

        result = await repo.upsert_from_catalog(incoming)
    finally:
        CurrentAsyncSessionContext.clear()

    assert existing.title == "Tokens (revisado)"
    # estado de transcrição não pode ser tocado pelo upsert de catálogo
    assert existing.transcript_status == "ready"
    assert existing.content_hash == "h"
    assert result.title == "Tokens (revisado)"
    assert result.transcript_status == TranscriptStatus.READY
    assert result.content_hash == "h"
    # não deve ter criado um model novo — só atualizou o existente
    assert session.added == []
    assert session.flush_calls == 1
    assert session.refreshed == [existing]


@pytest.mark.asyncio
async def test_save_raises_not_found_error_when_lesson_does_not_exist(fake_session):
    repo = LessonRepository()
    lesson = Lesson(
        uuid=uuid4(),
        platform_video_id="inexistente",
        program_slug="base",
        module_slug="modulo-1",
        video_slug="aula-1",
        title="Tokens",
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
    )

    with pytest.raises(NotFoundError):
        await repo.save(lesson)


@pytest.mark.asyncio
async def test_replace_for_lesson_deletes_before_adding_new_models(fake_session):
    lesson_id = uuid4()
    repo = LessonChunkRepository()

    chunks = [
        LessonChunk(
            uuid=uuid4(),
            lesson_id=lesson_id,
            ordinal=0,
            content="trecho 0",
            start_seconds=0.0,
            end_seconds=9.0,
            embedding=[0.0] * 1536,
        )
    ]

    await repo.replace_for_lesson(lesson_id, chunks)

    # o DELETE precisa ser a primeira instrução recebida pela sessão
    assert len(fake_session.executed_statements) == 1
    delete_sql = _compiled(fake_session.executed_statements[0])
    assert "DELETE FROM lesson_chunks" in delete_sql
    assert str(lesson_id).replace("-", "") in delete_sql

    # e só depois do DELETE os novos models entram via add()
    assert len(fake_session.added) == 1
    assert fake_session.added[0].lesson_id == lesson_id
    assert fake_session.flush_calls == 1


class _Row:
    """Mimetiza uma linha nomeada devolvida por `select(...)` com colunas soltas."""

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.mark.asyncio
async def test_search_similar_scopes_to_the_lesson_excludes_null_embeddings_and_has_no_threshold(
    fake_session,
):
    lesson_id = uuid4()
    repo = LessonChunkRepository()

    await repo.search_similar(lesson_id, [0.0] * 1536)

    assert len(fake_session.executed_statements) == 1
    sql = _compiled(fake_session.executed_statements[0])
    assert f"lesson_chunks.lesson_id = '{str(lesson_id).replace('-', '')}'" in sql
    # nullable: distância contra embedding nulo é indefinida (ruling C3)
    assert "lesson_chunks.embedding IS NOT NULL" in sql
    assert "ORDER BY lesson_chunks.embedding <=>" in sql
    # default top_k vem de settings.MENTOR_TOP_K, sem corte por distância
    assert "LIMIT 6" in sql
    assert "0.55" not in sql
    assert "RAG_MAX_DISTANCE" not in sql


@pytest.mark.asyncio
async def test_search_similar_maps_each_row_to_a_lesson_citation_with_the_timestamp():
    row = _Row(
        content="sobre autorregressão",
        start_seconds=750.4,
        title="Aula v-cite",
        program_slug="base",
        module_slug="m1",
        video_slug="aula-v-cite",
        distance=0.12,
    )
    session = FakeSession(execute_results=[FakeResult(rows=[row])])
    CurrentAsyncSessionContext.set(session)
    try:
        repo = LessonChunkRepository()
        rows = await repo.search_similar(uuid4(), [0.0] * 1536)
    finally:
        CurrentAsyncSessionContext.clear()

    assert len(rows) == 1
    snippet, distance = rows[0]
    assert snippet.content == "sobre autorregressão"
    assert snippet.citation.source_type == "lesson"
    assert snippet.citation.url == "/programs/base/m1/aula-v-cite?t=750"
    assert snippet.citation.title == "Aula v-cite"
    assert distance == 0.12
