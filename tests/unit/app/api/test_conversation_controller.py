"""Unidade do que dá para testar sem sessão de banco/HTTP: o helper que monta
o `extra_config` do modo mentor (C5). A wiring completa do controller (400 sem
lesson_id, 403 em acesso negado, mode/lesson_id/extra_config chegando ao
runner) está coberta em tests/integration/api/test_ask_mentor_entitlement.py —
precisa do Postgres local."""

from uuid import uuid4

from src.app.api.controllers.conversation_controller import build_mentor_extra_config
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus


def _lesson() -> Lesson:
    return Lesson(
        uuid=uuid4(), platform_video_id="v1", program_slug="base", module_slug="m1",
        video_slug="a1", title="Tokens", provider="PANDA_VIDEO", provider_ref="r",
        transcript_status=TranscriptStatus.READY,
    )


def test_extra_config_has_exactly_the_five_keys_c5():
    lesson = _lesson()
    config = build_mentor_extra_config(lesson)
    assert set(config) == {
        "lesson_id", "lesson_distances", "question_embedding",
        "lesson_platform_video_id", "lesson_program_slug",
    }


def test_lesson_id_is_the_internal_uuid_not_the_platform_video_id():
    """C1: o escopo da tool é `lessons.uuid`, não `platform_video_id`."""
    lesson = _lesson()
    config = build_mentor_extra_config(lesson)
    assert config["lesson_id"] == lesson.uuid
    assert config["lesson_platform_video_id"] == "v1"
    assert config["lesson_id"] != config["lesson_platform_video_id"]


def test_the_two_pre_seeded_lists_start_empty():
    config = build_mentor_extra_config(_lesson())
    assert config["lesson_distances"] == []
    assert config["question_embedding"] == []


def test_program_slug_travels_for_the_prompt():
    config = build_mentor_extra_config(_lesson())
    assert config["lesson_program_slug"] == "base"
