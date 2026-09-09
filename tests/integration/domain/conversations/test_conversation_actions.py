from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.append_assistant_message_action import (
    AppendAssistantMessageAction,
)
from src.domain.conversations.actions.get_conversation_action import GetConversationAction
from src.domain.conversations.actions.list_conversations_action import ListConversationsAction
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.repositories.conversation_repository import ConversationRepository
from src.domain.shared.value_objects.citation import Citation
from src.support.core.exceptions import NotFoundError


async def _conv(db_session, user_email=None):
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    c = await ConversationRepository().create(Conversation(uuid4(), user_email, "T", now, now, None))
    await db_session.flush()
    return c


@pytest.mark.asyncio
async def test_append_assistant_persists_with_sources(db_session):
    conv = await _conv(db_session)
    cite = Citation("notion", "Doc", "https://n", "trecho", "pid")
    await AppendAssistantMessageAction().execute(conv.uuid, "resposta final", [cite])
    await db_session.flush()

    _, messages = await GetConversationAction().execute(conv.uuid, None)
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].content == "resposta final"
    assert messages[0].sources == [cite]


@pytest.mark.asyncio
async def test_append_assistant_persists_with_navigation(db_session):
    conv = await _conv(db_session)
    navigation = {"destination": {"route": "/students/123"}, "access": "allowed"}
    await AppendAssistantMessageAction().execute(conv.uuid, "vou te levar lá", [], navigation=navigation)
    await db_session.flush()

    _, messages = await GetConversationAction().execute(conv.uuid, None)
    assert len(messages) == 1
    assert messages[0].navigation == navigation


@pytest.mark.asyncio
async def test_append_assistant_persists_with_navigation_none_by_default(db_session):
    conv = await _conv(db_session)
    await AppendAssistantMessageAction().execute(conv.uuid, "resposta sem navegação", [])
    await db_session.flush()

    _, messages = await GetConversationAction().execute(conv.uuid, None)
    assert len(messages) == 1
    assert messages[0].navigation is None


@pytest.mark.asyncio
async def test_get_conversation_not_found_raises(db_session):
    with pytest.raises(NotFoundError):
        await GetConversationAction().execute(uuid4(), None)


@pytest.mark.asyncio
async def test_get_conversation_denies_other_owner(db_session):
    # ADR-0017: conversa de outro usuário é 404 — nunca revela que existe.
    conv = await _conv(db_session, user_email="a@x.com")
    with pytest.raises(NotFoundError):
        await GetConversationAction().execute(conv.uuid, "b@x.com")


@pytest.mark.asyncio
async def test_list_conversations_by_user(db_session):
    await _conv(db_session, user_email="a@x.com")
    result = await ListConversationsAction().execute("a@x.com")
    assert all(c.user_email == "a@x.com" for c in result)
    assert len(result) >= 1
