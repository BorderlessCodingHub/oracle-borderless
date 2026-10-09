from uuid import uuid4

import pytest
from sqlalchemy import text

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.settings import settings


def _catalog_lesson(video_id: str = "v1", title: str = "Tokens", program_slug: str = "base") -> Lesson:
    return Lesson(
        uuid=uuid4(),
        platform_video_id=video_id,
        program_slug=program_slug,
        module_slug="modulo-1",
        video_slug="aula-1",
        title=title,
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
    )


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_without_losing_transcript_state(db_session):
    repo = LessonRepository()

    created = await repo.upsert_from_catalog(_catalog_lesson())
    created.transcript_status = TranscriptStatus.READY
    created.transcript_text = "conteúdo"
    created.content_hash = "hash-1"
    await repo.save(created)

    again = await repo.upsert_from_catalog(_catalog_lesson(title="Tokens (revisado)"))

    assert again.uuid == created.uuid
    assert again.title == "Tokens (revisado)"
    assert again.transcript_status == TranscriptStatus.READY
    assert again.content_hash == "hash-1"


@pytest.mark.asyncio
async def test_list_pending_returns_pending_and_failed_under_the_attempt_ceiling(db_session):
    # `program_slug` único: linhas committed por OUTRO teste na mesma tabela
    # compartilhada não podem quebrar a igualdade de conjunto abaixo.
    program = f"base-{uuid4().hex[:8]}"
    repo = LessonRepository()

    pending = await repo.upsert_from_catalog(_catalog_lesson("v-pending", program_slug=program))

    failed = await repo.upsert_from_catalog(_catalog_lesson("v-failed", program_slug=program))
    failed.transcript_status = TranscriptStatus.FAILED
    failed.attempts = 1
    await repo.save(failed)

    exhausted = await repo.upsert_from_catalog(_catalog_lesson("v-exhausted", program_slug=program))
    exhausted.transcript_status = TranscriptStatus.FAILED
    exhausted.attempts = 3
    await repo.save(exhausted)

    ready = await repo.upsert_from_catalog(_catalog_lesson("v-ready", program_slug=program))
    ready.transcript_status = TranscriptStatus.READY
    await repo.save(ready)

    # claim recente (updated_at fresco) — outra execução está trabalhando nela agora
    transcribing_fresh = await repo.upsert_from_catalog(
        _catalog_lesson("v-transcribing-fresh", program_slug=program)
    )
    transcribing_fresh.transcript_status = TranscriptStatus.TRANSCRIBING
    transcribing_fresh.attempts = 1
    await repo.save(transcribing_fresh)

    ids = {l.platform_video_id for l in await repo.list_pending(program, max_attempts=3)}
    assert ids == {"v-pending", "v-failed"}


@pytest.mark.asyncio
async def test_list_pending_recovers_stale_transcribing_but_not_fresh_ones(db_session):
    """Claim `transcribing` mais velho que `MENTOR_CLAIM_STALE_MINUTES` volta
    ao lote (processo morreu entre o claim e o save final); um `transcribing`
    recém-criado é claim de OUTRA execução em andamento e fica de fora."""
    program = f"base-{uuid4().hex[:8]}"
    repo = LessonRepository()

    stale = await repo.upsert_from_catalog(_catalog_lesson("v-stale", program_slug=program))
    stale.transcript_status = TranscriptStatus.TRANSCRIBING
    stale.attempts = 1
    await repo.save(stale)
    await db_session.execute(
        text(
            "UPDATE lessons SET updated_at = now() - interval '200 minutes' "
            "WHERE platform_video_id = :id"
        ),
        {"id": "v-stale"},
    )

    fresh = await repo.upsert_from_catalog(_catalog_lesson("v-fresh", program_slug=program))
    fresh.transcript_status = TranscriptStatus.TRANSCRIBING
    fresh.attempts = 1
    await repo.save(fresh)

    ids = {l.platform_video_id for l in await repo.list_pending(program, max_attempts=3)}
    assert ids == {"v-stale"}


@pytest.mark.asyncio
async def test_replace_for_lesson_is_idempotent(db_session):
    lesson = await LessonRepository().upsert_from_catalog(_catalog_lesson("v-chunks"))
    chunks_repo = LessonChunkRepository()

    def chunk(i: int) -> LessonChunk:
        return LessonChunk(
            uuid=uuid4(), lesson_id=lesson.uuid, ordinal=i, content=f"trecho {i}",
            start_seconds=float(i * 10), end_seconds=float(i * 10 + 9),
            embedding=[1.0] + [0.0] * (settings.EMBEDDING_DIM - 1),
        )

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0), chunk(1)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 2

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 1
