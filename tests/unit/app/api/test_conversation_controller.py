"""Unidade do que dá para testar sem sessão de banco/HTTP: o helper que monta
o `extra_config` do modo mentor (C5) e o invariante do ADR-0013 (observabilidade
nunca derruba a resposta). A wiring completa do controller (400 sem lesson_id,
403 em acesso negado, mode/lesson_id/extra_config chegando ao runner) está
coberta em tests/integration/api/test_ask_mentor_entitlement.py — precisa do
Postgres local."""

from uuid import uuid4

import pytest

import src.app.api.controllers.conversation_controller as ctrl
from src.app.api.controllers.conversation_controller import _persist_turn, build_mentor_extra_config
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


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


class _FakeNestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def begin_nested(self):
        return _FakeNestedTransaction()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_a_trace_recording_failure_never_blocks_the_answer_from_being_persisted(monkeypatch):
    """ADR-0013: 'o call site fica sob try/except que loga e engole. Uma linha
    de trace perdida é aceitável; um turno perdido não.' `RecordTurnTraceAction`
    quebra (ex.: overflow de coluna); a resposta do assistente, gravada logo
    depois no mesmo `_persist_turn`, ainda assim tem que ser persistida."""
    monkeypatch.setattr(
        "src.support.core.session_scope.AsyncSessionLocal", lambda: _FakeSession()
    )

    async def _raise(self, conversation_id, draft):
        raise RuntimeError("boom: coluna estourou")

    monkeypatch.setattr(ctrl.RecordTurnTraceAction, "execute", _raise)

    appended: dict = {}

    async def _append(self, conversation_id, content, citations, navigation=None):
        appended["content"] = content

    monkeypatch.setattr(ctrl.AppendAssistantMessageAction, "execute", _append)

    draft = TurnTraceDraft(question="quando usar PSP?")
    await _persist_turn(uuid4(), draft, "resposta apesar do trace quebrar", [], None)

    assert appended["content"] == "resposta apesar do trace quebrar"
