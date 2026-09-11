"""O body do POST /conversations/ask espelha `astream_events(input, config)`
(ADR-0021): `input.question`, `config.run_id`, `config.configurable.thread_id`.
UUIDs canônicos e pergunta não vazia — tudo 422, nunca evento no stream."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.app.api.requests.stream_events_request import StreamEventsRequest


def _body(question="como funciona a renovação?", thread_id=None, run_id=None) -> dict:
    return {
        "input": {"question": question},
        "config": {"run_id": run_id or str(uuid4()), "configurable": {"thread_id": thread_id or str(uuid4())}},
    }


def test_a_valid_body_exposes_question_conversation_id_and_run_id():
    body = _body()

    req = StreamEventsRequest.model_validate(body)

    assert req.question == "como funciona a renovação?"
    assert req.conversation_id == UUID(body["config"]["configurable"]["thread_id"])
    assert req.run_id == body["config"]["run_id"]


def test_question_is_stripped():
    assert StreamEventsRequest.model_validate(_body("  segunda  ")).question == "segunda"


def test_blank_question_is_rejected():
    with pytest.raises(ValidationError, match="vazia"):
        StreamEventsRequest.model_validate(_body("   "))


def test_non_uuid_ids_are_rejected():
    with pytest.raises(ValidationError, match="thread_id deve ser um UUID"):
        StreamEventsRequest.model_validate(_body(thread_id="not-a-uuid"))
    with pytest.raises(ValidationError, match="run_id deve ser um UUID"):
        StreamEventsRequest.model_validate(_body(run_id="123"))


def test_missing_sections_are_rejected():
    with pytest.raises(ValidationError):
        StreamEventsRequest.model_validate({"input": {"question": "x"}})
    with pytest.raises(ValidationError):
        StreamEventsRequest.model_validate({"input": {"question": "x"}, "config": {"run_id": str(uuid4())}})


def test_extra_keys_are_ignored_at_every_level():
    body = _body()
    body["input"]["history"] = [{"role": "user", "content": "x"}]
    body["config"]["tags"] = ["ui"]
    body["config"]["recursion_limit"] = 5
    body["config"]["configurable"]["deps"] = "não pode injetar"
    body["version"] = "v2"

    req = StreamEventsRequest.model_validate(body)

    assert req.question == "como funciona a renovação?"
    assert not hasattr(req.config.configurable, "deps")


def test_mode_and_locale_default_to_chat_and_pt_br():
    req = StreamEventsRequest.model_validate(_body())
    assert (req.mode, req.locale) == ("chat", "pt-BR")


def test_mode_navigate_and_locale_en_are_accepted():
    body = _body()
    body["input"].update({"mode": "navigate", "locale": "en"})
    req = StreamEventsRequest.model_validate(body)
    assert (req.mode, req.locale) == ("navigate", "en")


@pytest.mark.parametrize("field,value", [("mode", "fly"), ("locale", "es")])
def test_unknown_mode_or_locale_is_rejected(field, value):
    body = _body()
    body["input"][field] = value
    with pytest.raises(ValidationError):
        StreamEventsRequest.model_validate(body)


def test_ids_are_canonicalised():
    """Um UUID válido mas não-canônico (sem dashes, ou com case diferente) vira
    a forma canônica — é o que entra no run_id do LangSmith e no
    agent_traces.langsmith_run_id."""
    req = StreamEventsRequest.model_validate(_body(
        run_id="123e4567e89b12d3a456426614174000",
        thread_id="123E4567-E89B-12D3-A456-426614174001",
    ))

    assert req.run_id == "123e4567-e89b-12d3-a456-426614174000"
    assert str(req.conversation_id) == "123e4567-e89b-12d3-a456-426614174001"
