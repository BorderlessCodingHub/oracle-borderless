from uuid import uuid4

import pytest

from src.domain.lessons.actions.check_lesson_access_action import (
    CheckLessonAccessAction,
    LessonAccessDeniedError,
)
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus


def a_lesson(status=TranscriptStatus.READY) -> Lesson:
    return Lesson(
        uuid=uuid4(), platform_video_id="v1", program_slug="base", module_slug="m1",
        video_slug="a1", title="Tokens", provider="PANDA_VIDEO", provider_ref="r",
        transcript_status=status,
    )


class FakeRepo:
    def __init__(self, lesson):
        self._lesson = lesson

    async def get_by_platform_video_id(self, video_id):
        return self._lesson


class FakeAccess:
    def __init__(self, allowed=True, raises=None):
        self.allowed = allowed
        self.raises = raises
        self.calls: list[tuple] = []

    async def has_access(self, bearer, program_slug, module_slug, video_slug):
        self.calls.append((bearer, program_slug, module_slug, video_slug))
        if self.raises:
            raise self.raises
        return self.allowed


@pytest.mark.asyncio
async def test_allows_and_returns_the_lesson():
    action = CheckLessonAccessAction(access_client=FakeAccess(True), lesson_repo=FakeRepo(a_lesson()))
    lesson = await action.execute(bearer="tok", platform_video_id="v1")
    assert lesson.platform_video_id == "v1"


@pytest.mark.asyncio
async def test_denies_when_the_platform_says_no():
    action = CheckLessonAccessAction(access_client=FakeAccess(False), lesson_repo=FakeRepo(a_lesson()))
    with pytest.raises(LessonAccessDeniedError):
        await action.execute(bearer="tok", platform_video_id="v1")


@pytest.mark.asyncio
async def test_an_unknown_lesson_is_denied_not_a_crash():
    action = CheckLessonAccessAction(access_client=FakeAccess(True), lesson_repo=FakeRepo(None))
    with pytest.raises(LessonAccessDeniedError):
        await action.execute(bearer="tok", platform_video_id="ghost")


@pytest.mark.asyncio
async def test_platform_unreachable_denies_fail_closed():
    """Ao contrário do fail-open de 10 min da autenticação: lá o risco é
    derrubar sessão válida, aqui é entregar conteúdo pago (spec §5)."""
    action = CheckLessonAccessAction(
        access_client=FakeAccess(raises=RuntimeError("api fora")), lesson_repo=FakeRepo(a_lesson())
    )
    with pytest.raises(LessonAccessDeniedError):
        await action.execute(bearer="tok", platform_video_id="v1")


@pytest.mark.asyncio
async def test_the_bearer_is_forwarded_so_the_platform_judges_the_real_user():
    access = FakeAccess(True)
    await CheckLessonAccessAction(access_client=access, lesson_repo=FakeRepo(a_lesson())).execute(
        bearer="tok-do-aluno", platform_video_id="v1"
    )
    assert access.calls[0][0] == "tok-do-aluno"


# --- M1: o corpo do 403 é opaco nos três casos ------------------------------


@pytest.mark.asyncio
async def test_unknown_and_denied_lessons_raise_the_exact_same_opaque_message():
    """M1: um cliente não pode distinguir 'aula não indexada' de 'aula
    indexada mas eu não comprei' tentando ids ao acaso — as duas mensagens
    (e a de entitlement indisponível) precisam ser IDÊNTICAS."""
    unknown = CheckLessonAccessAction(access_client=FakeAccess(True), lesson_repo=FakeRepo(None))
    denied = CheckLessonAccessAction(access_client=FakeAccess(False), lesson_repo=FakeRepo(a_lesson()))
    unavailable = CheckLessonAccessAction(
        access_client=FakeAccess(raises=RuntimeError("api fora")), lesson_repo=FakeRepo(a_lesson())
    )

    with pytest.raises(LessonAccessDeniedError) as unknown_exc:
        await unknown.execute(bearer="tok", platform_video_id="ghost")
    with pytest.raises(LessonAccessDeniedError) as denied_exc:
        await denied.execute(bearer="tok", platform_video_id="v1")
    with pytest.raises(LessonAccessDeniedError) as unavailable_exc:
        await unavailable.execute(bearer="tok", platform_video_id="v1")

    messages = {str(unknown_exc.value), str(denied_exc.value), str(unavailable_exc.value)}
    assert messages == {"sem acesso a esta aula"}
