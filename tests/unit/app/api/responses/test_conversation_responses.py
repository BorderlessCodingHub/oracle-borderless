from datetime import datetime, timezone
from uuid import uuid4

from src.app.api.responses.conversation_responses import MessageResponse
from src.domain.conversations.entities.message import Message
from src.domain.shared.value_objects.citation import Citation


def _message(**overrides) -> Message:
    base = dict(
        uuid=uuid4(),
        conversation_id=uuid4(),
        role="assistant",
        content="resposta",
        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        sources=None,
        navigation=None,
    )
    base.update(overrides)
    return Message(**base)


def test_from_entity_exposes_navigation_when_present():
    navigation = {"destination": {"route": "/students/123"}, "access": "allowed"}
    message = _message(navigation=navigation)

    response = MessageResponse.from_entity(message)

    assert response.navigation == navigation


def test_from_entity_navigation_defaults_to_none():
    response = MessageResponse.from_entity(_message())
    assert response.navigation is None


def test_from_entity_still_maps_role_content_and_sources():
    cite = Citation("notion", "Doc", "https://n", "trecho", "pid-1")
    message = _message(sources=[cite])

    response = MessageResponse.from_entity(message)

    assert response.role == "assistant"
    assert response.content == "resposta"
    assert response.sources[0].source_type == "notion"


def test_summary_exposes_mode():
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.app.api.responses.conversation_responses import ConversationSummaryResponse
    from src.domain.conversations.entities.conversation import Conversation

    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    conv = Conversation(uuid4(), "a@x.com", "T", now, now, None, mode="navigate")

    assert ConversationSummaryResponse.from_entity(conv).mode == "navigate"
