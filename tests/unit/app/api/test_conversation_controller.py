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
from src.app.api.requests.stream_events_request import StreamEventsRequest
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.domain.users.actions.resolve_bearer_action import SOURCE_PLATFORM_BEARER
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.core.context import CurrentRequestContext
from src.support.core.exceptions import NotFoundError
from tests.fakes.stream_events import ask_body


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


# --- I2 (ruling C7): MENTOR_ENABLED como kill switch de verdade -----------


@pytest.mark.asyncio
async def test_mentor_disabled_is_404_before_the_entitlement_check_or_any_work(monkeypatch):
    """Sem passar por `CheckLessonAccessAction`/`OpenTurnAction` — o desligamento
    vale ANTES de qualquer trabalho, inclusive antes do 400 de lesson_id
    ausente (o teste usa um body sem lesson_id de propósito: se o kill switch
    não disparasse primeiro, o próximo erro seria DomainError, não NotFoundError)."""
    monkeypatch.setattr(ctrl.settings, "MENTOR_ENABLED", False)

    async def _boom(*args, **kwargs):
        raise AssertionError("OpenTurnAction não deveria rodar com o mentor desligado")

    monkeypatch.setattr(ctrl.OpenTurnAction, "execute", _boom)

    user = AuthenticatedUser(id="u1", email="mentor-off@x.com")
    CurrentRequestContext.set_user(user)
    try:
        body = ask_body("o que é PSP?", mode="mentor")  # sem lesson_id
        data = StreamEventsRequest(**body)

        with pytest.raises(NotFoundError):
            await ctrl.ConversationController.ask(data)
    finally:
        CurrentRequestContext.clear()


# --- I3: turno mentor não paga o round-trip do catálogo de navegação -----


@pytest.mark.asyncio
async def test_build_extra_config_skips_the_navigation_catalog_fetch_for_mentor_mode(monkeypatch):
    calls = {"n": 0}

    class _BoomCatalog:
        async def describe(self, token):
            calls["n"] += 1
            return "catálogo ao vivo"

    monkeypatch.setattr(ctrl, "NavigationCatalog", _BoomCatalog)

    user = AuthenticatedUser(
        id="u1", email="mentor@x.com", session_source=SOURCE_PLATFORM_BEARER,
        platform_access_token="tok",
    )

    config = await ctrl._build_extra_config(user, "mentor")

    assert calls["n"] == 0
    assert config["navigation_enabled"] is False
    assert config["navigation_catalog_text"] is None


@pytest.mark.asyncio
async def test_build_extra_config_still_fetches_the_catalog_for_chat_mode_platform_bearer(monkeypatch):
    """Controle: I3 não pode quebrar o caminho existente — chat/navigate numa
    sessão platform_bearer continua buscando o catálogo ao vivo."""
    calls = {"n": 0}

    class _Catalog:
        async def describe(self, token):
            calls["n"] += 1
            return "catálogo ao vivo"

    monkeypatch.setattr(ctrl, "NavigationCatalog", _Catalog)

    user = AuthenticatedUser(
        id="u1", email="chat@x.com", session_source=SOURCE_PLATFORM_BEARER,
        platform_access_token="tok",
    )

    config = await ctrl._build_extra_config(user, "chat")

    assert calls["n"] == 1
    assert config["navigation_enabled"] is True
    assert config["navigation_catalog_text"] == "catálogo ao vivo"


# --- T5: a ORDEM importa — absorve o engine primeiro, mentor por cima -----


def test_finalize_mentor_trace_lets_mentor_signals_overwrite_the_engine_absorb():
    """Simula a sequência do controller: `_absorb_engine_metrics`-equivalente
    zera intent/retrieval_kept (como faria um `signals` de um turno que nunca
    passou por gate/retrieve genérico), DEPOIS `apply_mentor_signals` escreve
    por cima com o que a tool `search_lesson` preencheu em `extra_config`. Se a
    ordem estivesse invertida, este teste falharia com intent=None."""
    draft = TurnTraceDraft(question="quando usar PSP?")
    draft.intent = None
    draft.retrieval_kept = 0

    extra_config = {
        "lesson_distances": [0.2, 0.4],
        "question_embedding": [0.1, 0.2],
        "lesson_platform_video_id": "video-123",
        "lesson_program_slug": "base",
    }

    ctrl.finalize_mentor_trace(draft, "mentor", extra_config)

    assert draft.intent == "mentor"
    assert draft.retrieval_kept == 2


def test_finalize_mentor_trace_leaves_chat_turns_untouched():
    draft = TurnTraceDraft(question="oi")
    draft.intent = "chit_chat"
    draft.retrieval_kept = 3

    ctrl.finalize_mentor_trace(draft, "chat", {})

    assert draft.intent == "chit_chat"
    assert draft.retrieval_kept == 3
