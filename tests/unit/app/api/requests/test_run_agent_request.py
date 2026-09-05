"""O body do POST /conversations/ask é o RunAgentInput do AG-UI (ADR-0019), com
três regras nossas por cima: threadId e runId são UUIDs, e a última mensagem é
do usuário e não está vazia. Tudo isso é 422 — nunca evento no stream."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.app.api.requests.run_agent_request import RunAgentRequest


def _body(**overrides) -> dict:
    body = {
        "threadId": str(uuid4()),
        "runId": str(uuid4()),
        "messages": [{"id": "m1", "role": "user", "content": "como funciona a renovação?"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    body.update(overrides)
    return body


def test_a_valid_body_exposes_question_and_conversation_id():
    body = _body()

    req = RunAgentRequest.model_validate(body)

    assert req.question == "como funciona a renovação?"
    assert req.conversation_id == UUID(body["threadId"])
    assert req.run_id == body["runId"]


def test_question_is_the_last_user_message_and_the_rest_is_ignored():
    req = RunAgentRequest.model_validate(_body(messages=[
        {"id": "m1", "role": "user", "content": "primeira"},
        {"id": "m2", "role": "assistant", "content": "resposta"},
        {"id": "m3", "role": "user", "content": "  segunda  "},
    ]))

    assert req.question == "segunda"


@pytest.mark.parametrize("field", ["threadId", "runId"])
def test_non_uuid_ids_are_rejected(field):
    with pytest.raises(ValidationError, match="UUID"):
        RunAgentRequest.model_validate(_body(**{field: "not-a-uuid"}))


def test_last_message_must_be_from_the_user():
    with pytest.raises(ValidationError, match="usuário"):
        RunAgentRequest.model_validate(_body(messages=[
            {"id": "m1", "role": "user", "content": "oi"},
            {"id": "m2", "role": "assistant", "content": "olá"},
        ]))


def test_empty_messages_are_rejected():
    with pytest.raises(ValidationError, match="messages"):
        RunAgentRequest.model_validate(_body(messages=[]))


def test_blank_question_is_rejected():
    with pytest.raises(ValidationError, match="vazia"):
        RunAgentRequest.model_validate(_body(messages=[{"id": "m1", "role": "user", "content": "   "}]))
