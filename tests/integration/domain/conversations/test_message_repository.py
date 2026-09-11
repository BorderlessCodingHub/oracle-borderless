from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.conversations.repositories.conversation_repository import ConversationRepository
from src.domain.conversations.repositories.message_repository import MessageRepository


async def _new_conversation(db_session) -> "Conversation":
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    conv = await ConversationRepository().create(
        Conversation(uuid4(), None, "T", now, now, None)
    )
    await db_session.flush()
    return conv


def _msg(conversation_id, role, content):
    # uuid7 (não uuid4) para espelhar a produção: o tiebreak de ordenação do repo é por
    # uuid, e só é determinístico porque uuid7 é monotônico crescente por inserção.
    return Message(uuid7(), conversation_id, role, content, datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_append_and_list_chronological(db_session):
    conv = await _new_conversation(db_session)
    repo = MessageRepository()
    await repo.append(_msg(conv.uuid, "user", "pergunta 1"))
    await repo.append(_msg(conv.uuid, "assistant", "resposta 1"))
    await db_session.flush()

    msgs = await repo.list_by_conversation(conv.uuid)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert [m.content for m in msgs] == ["pergunta 1", "resposta 1"]


@pytest.mark.asyncio
async def test_load_recent_respects_token_budget(db_session, monkeypatch):
    # Budget minúsculo: cada mensagem de 40 chars ~= 10 tokens (len//4).
    monkeypatch.setattr("src.domain.conversations.repositories.message_repository.settings.MEMORY_RECENCY_TOKEN_BUDGET", 15)
    conv = await _new_conversation(db_session)
    repo = MessageRepository()
    for i in range(5):
        await repo.append(_msg(conv.uuid, "user", "x" * 40))  # ~10 tokens cada
        await db_session.flush()

    recent = await repo.load_recent(conv.uuid)
    # 15 de budget: cabe a última (10) + a próxima excede (20>15) → só 1
    assert len(recent) == 1
    assert recent[0].role == "user"


@pytest.mark.asyncio
async def test_order_is_deterministic_within_same_transaction(db_session):
    # Regressão: created_at é server-side func.now() = timestamp de início da transação,
    # então três turnos gravados na MESMA transação (sem commit entre eles) recebem
    # created_at idêntico. A ordem só é determinística por causa do tiebreak por uuid7
    # (client-side, monotônico crescente) — não por sorte da ordem física das linhas.
    conv = await _new_conversation(db_session)
    repo = MessageRepository()
    await repo.append(_msg(conv.uuid, "user", "primeira"))
    await repo.append(_msg(conv.uuid, "assistant", "segunda"))
    await repo.append(_msg(conv.uuid, "user", "terceira"))
    await db_session.flush()

    msgs = await repo.list_by_conversation(conv.uuid)
    assert [m.content for m in msgs] == ["primeira", "segunda", "terceira"]

    recent = await repo.load_recent(conv.uuid)
    assert [m.content for m in recent] == ["primeira", "segunda", "terceira"]


@pytest.mark.asyncio
async def test_append_and_list_roundtrips_navigation(db_session):
    conv = await _new_conversation(db_session)
    repo = MessageRepository()
    navigation = {"destination": {"route": "/students/123"}, "access": "allowed"}
    with_nav = Message(uuid7(), conv.uuid, "assistant", "vou te levar lá", datetime.now(timezone.utc), navigation=navigation)
    without_nav = Message(uuid7(), conv.uuid, "assistant", "sem navegação", datetime.now(timezone.utc))
    await repo.append(with_nav)
    await repo.append(without_nav)
    await db_session.flush()

    msgs = await repo.list_by_conversation(conv.uuid)
    assert msgs[0].navigation == navigation
    assert msgs[1].navigation is None


@pytest.mark.asyncio
async def test_append_bumps_conversation_updated_at(db_session):
    conv = await _new_conversation(db_session)
    before = (await ConversationRepository().get_by_id(conv.uuid)).updated_at
    await MessageRepository().append(_msg(conv.uuid, "user", "nova"))
    await db_session.flush()
    after = (await ConversationRepository().get_by_id(conv.uuid)).updated_at
    assert after >= before
