import pytest

from src.domain.lessons.actions.sync_program_lessons_action import SyncProgramLessonsAction
from src.support.clients.borderless.borderless_lessons_client import CatalogLesson


class FakeClient:
    def __init__(self, rows):
        self._rows = rows

    async def list_program_lessons(self, program_slug):
        return self._rows


class FakeRepo:
    def __init__(self):
        self.upserted = []

    async def upsert_from_catalog(self, lesson):
        self.upserted.append(lesson)
        return lesson


def row(video_id="v1") -> CatalogLesson:
    return CatalogLesson(
        platform_video_id=video_id, program_slug="base", module_slug="m1",
        video_slug=f"aula-{video_id}", title="Tokens", provider="PANDA_VIDEO",
        provider_ref=f"ref-{video_id}", duration_seconds=None,
    )


@pytest.mark.asyncio
async def test_every_catalog_row_becomes_an_upsert():
    repo = FakeRepo()
    action = SyncProgramLessonsAction(lessons_client=FakeClient([row("v1"), row("v2")]), lesson_repo=repo)

    lessons = await action.execute("base")

    assert [l.platform_video_id for l in lessons] == ["v1", "v2"]
    assert len(repo.upserted) == 2


@pytest.mark.asyncio
async def test_new_lessons_start_pending():
    from src.domain.lessons.enums import TranscriptStatus

    action = SyncProgramLessonsAction(lessons_client=FakeClient([row()]), lesson_repo=FakeRepo())
    lessons = await action.execute("base")
    assert lessons[0].transcript_status == TranscriptStatus.PENDING


@pytest.mark.asyncio
async def test_an_empty_catalog_is_not_an_error():
    action = SyncProgramLessonsAction(lessons_client=FakeClient([]), lesson_repo=FakeRepo())
    assert await action.execute("base") == []
