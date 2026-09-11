from uuid import uuid4

import pytest

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository


def _catalog_lesson(video_id: str = "v1", title: str = "Tokens") -> Lesson:
    return Lesson(
        uuid=uuid4(),
        platform_video_id=video_id,
        program_slug="base",
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
    repo = LessonRepository()

    pending = await repo.upsert_from_catalog(_catalog_lesson("v-pending"))

    failed = await repo.upsert_from_catalog(_catalog_lesson("v-failed"))
    failed.transcript_status = TranscriptStatus.FAILED
    failed.attempts = 1
    await repo.save(failed)

    exhausted = await repo.upsert_from_catalog(_catalog_lesson("v-exhausted"))
    exhausted.transcript_status = TranscriptStatus.FAILED
    exhausted.attempts = 3
    await repo.save(exhausted)

    ready = await repo.upsert_from_catalog(_catalog_lesson("v-ready"))
    ready.transcript_status = TranscriptStatus.READY
    await repo.save(ready)

    ids = {l.platform_video_id for l in await repo.list_pending("base", max_attempts=3)}
    assert ids == {"v-pending", "v-failed"}


@pytest.mark.asyncio
async def test_replace_for_lesson_is_idempotent(db_session):
    lesson = await LessonRepository().upsert_from_catalog(_catalog_lesson("v-chunks"))
    chunks_repo = LessonChunkRepository()

    def chunk(i: int) -> LessonChunk:
        return LessonChunk(
            uuid=uuid4(), lesson_id=lesson.uuid, ordinal=i, content=f"trecho {i}",
            start_seconds=float(i * 10), end_seconds=float(i * 10 + 9),
            embedding=[0.0] * 1536,
        )

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0), chunk(1)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 2

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 1
