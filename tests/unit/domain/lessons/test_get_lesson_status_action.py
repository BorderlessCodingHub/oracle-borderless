from uuid import uuid4

import pytest

from src.domain.lessons.actions.get_lesson_status_action import GetLessonStatusAction
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus


def a_lesson(status) -> Lesson:
    return Lesson(
        uuid=uuid4(), platform_video_id="v1", program_slug="base", module_slug="m1",
        video_slug="a1", title="T", provider="PANDA_VIDEO", provider_ref="r",
        transcript_status=status,
    )


class FakeLessons:
    def __init__(self, lesson):
        self._lesson = lesson

    async def get_by_platform_video_id(self, video_id):
        return self._lesson


class FakeChunks:
    def __init__(self, count):
        self._count = count

    async def count_for_lesson(self, lesson_id):
        return self._count


@pytest.mark.asyncio
async def test_a_ready_lesson_reports_its_chunk_count():
    action = GetLessonStatusAction(FakeLessons(a_lesson(TranscriptStatus.READY)), FakeChunks(42))
    assert await action.execute("v1") == {"status": "ready", "chunkCount": 42}


@pytest.mark.asyncio
async def test_an_unindexed_lesson_is_unknown_not_an_error():
    """A aba precisa saber a diferença entre 'ainda preparando' e 'não existe',
    para mostrar o estado vazio certo em vez de um erro."""
    action = GetLessonStatusAction(FakeLessons(None), FakeChunks(0))
    assert await action.execute("ghost") == {"status": "unknown", "chunkCount": 0}


@pytest.mark.asyncio
async def test_a_failed_lesson_reports_failed_with_zero_chunks():
    action = GetLessonStatusAction(FakeLessons(a_lesson(TranscriptStatus.FAILED)), FakeChunks(0))
    assert await action.execute("v1") == {"status": "failed", "chunkCount": 0}
