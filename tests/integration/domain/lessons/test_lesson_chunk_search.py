from uuid import uuid4

import pytest

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.settings import settings


def vec(first: float) -> list[float]:
    v = [0.0] * settings.EMBEDDING_DIM
    v[0] = first
    v[1] = 1.0 - abs(first)
    return v


async def make_lesson(video_id: str) -> Lesson:
    return await LessonRepository().upsert_from_catalog(
        Lesson(
            uuid=uuid4(), platform_video_id=video_id, program_slug="base",
            module_slug="m1", video_slug=f"aula-{video_id}", title=f"Aula {video_id}",
            provider="PANDA_VIDEO", provider_ref="ref",
        )
    )


@pytest.mark.asyncio
async def test_search_never_crosses_into_another_lesson(db_session):
    mine = await make_lesson("v-mine")
    other = await make_lesson("v-other")
    repo = LessonChunkRepository()

    await repo.replace_for_lesson(mine.uuid, [
        LessonChunk(uuid=uuid4(), lesson_id=mine.uuid, ordinal=0, content="minha aula",
                    start_seconds=0.0, end_seconds=5.0, embedding=vec(1.0)),
    ])
    await repo.replace_for_lesson(other.uuid, [
        LessonChunk(uuid=uuid4(), lesson_id=other.uuid, ordinal=0, content="outra aula",
                    start_seconds=0.0, end_seconds=5.0, embedding=vec(1.0)),
    ])

    rows = await repo.search_similar(mine.uuid, vec(1.0), top_k=10)

    assert len(rows) == 1
    assert rows[0][0].content == "minha aula"


@pytest.mark.asyncio
async def test_results_come_back_nearest_first_with_their_distance(db_session):
    lesson = await make_lesson("v-order")
    repo = LessonChunkRepository()
    await repo.replace_for_lesson(lesson.uuid, [
        LessonChunk(uuid=uuid4(), lesson_id=lesson.uuid, ordinal=0, content="longe",
                    start_seconds=0.0, end_seconds=1.0, embedding=vec(-1.0)),
        LessonChunk(uuid=uuid4(), lesson_id=lesson.uuid, ordinal=1, content="perto",
                    start_seconds=1.0, end_seconds=2.0, embedding=vec(1.0)),
    ])

    rows = await repo.search_similar(lesson.uuid, vec(1.0), top_k=2)

    assert [r[0].content for r in rows] == ["perto", "longe"]
    assert rows[0][1] < rows[1][1]


@pytest.mark.asyncio
async def test_there_is_no_distance_threshold_so_a_far_query_still_returns(db_session):
    """Deliberado (spec §4): cortar por distância recriaria a recusa que o
    mentor não deve ter. Quem julga relevância é o modelo."""
    lesson = await make_lesson("v-far")
    repo = LessonChunkRepository()
    await repo.replace_for_lesson(lesson.uuid, [
        LessonChunk(uuid=uuid4(), lesson_id=lesson.uuid, ordinal=0, content="qualquer coisa",
                    start_seconds=0.0, end_seconds=1.0, embedding=vec(1.0)),
    ])

    rows = await repo.search_similar(lesson.uuid, vec(-1.0), top_k=5)

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_citation_carries_the_lesson_url_with_the_timestamp(db_session):
    lesson = await make_lesson("v-cite")
    repo = LessonChunkRepository()
    await repo.replace_for_lesson(lesson.uuid, [
        LessonChunk(uuid=uuid4(), lesson_id=lesson.uuid, ordinal=0, content="sobre autorregressão",
                    start_seconds=750.4, end_seconds=800.0, embedding=vec(1.0)),
    ])

    snippet, _ = (await repo.search_similar(lesson.uuid, vec(1.0), top_k=1))[0]

    assert snippet.citation.source_type == "lesson"
    assert snippet.citation.url == "/programs/base/m1/aula-v-cite?t=750"
    assert snippet.citation.title == "Aula v-cite"
