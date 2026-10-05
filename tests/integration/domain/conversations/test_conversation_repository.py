from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, update

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.models.conversation import ConversationModel
from src.domain.conversations.repositories.conversation_repository import ConversationRepository


def _conv(user_email=None, title="T"):
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    return Conversation(uuid4(), user_email, title, now, now, None)


@pytest.mark.asyncio
async def test_create_then_get_by_id(db_session):
    repo = ConversationRepository()
    created = await repo.create(_conv(user_email="a@x.com", title="Primeira"))
    await db_session.flush()

    found = await repo.get_by_id(created.uuid)
    assert found is not None
    assert found.title == "Primeira"
    assert found.user_email == "a@x.com"


@pytest.mark.asyncio
async def test_list_by_user_filters_and_orders(db_session):
    repo = ConversationRepository()
    await repo.create(_conv(user_email="a@x.com", title="A1"))
    await repo.create(_conv(user_email="b@x.com", title="B1"))
    await db_session.flush()

    mine = await repo.list_by_user("a@x.com")
    assert [c.title for c in mine] == ["A1"]


@pytest.mark.asyncio
async def test_list_by_user_none_returns_ownerless(db_session):
    repo = ConversationRepository()
    await repo.create(_conv(user_email=None, title="Anon"))
    await repo.create(_conv(user_email="a@x.com", title="Owned"))
    await db_session.flush()

    anon = await repo.list_by_user(None)
    assert all(c.user_email is None for c in anon)
    assert "Anon" in [c.title for c in anon]


@pytest.mark.asyncio
async def test_list_by_user_excludes_soft_deleted(db_session):
    repo = ConversationRepository()
    created = await repo.create(_conv(user_email="sd@x.com", title="Deletada"))
    await db_session.flush()

    await db_session.execute(
        update(ConversationModel)
        .where(ConversationModel.uuid == created.uuid)
        .values(deleted_at=func.now())
    )
    await db_session.flush()

    result = await repo.list_by_user("sd@x.com")
    assert created.uuid not in [c.uuid for c in result]


@pytest.mark.asyncio
async def test_list_by_user_orders_by_updated_at_desc(db_session):
    repo = ConversationRepository()
    c_old = await repo.create(_conv(user_email="ord@x.com", title="Antiga"))
    c_new = await repo.create(_conv(user_email="ord@x.com", title="Nova"))
    await db_session.flush()

    await db_session.execute(
        update(ConversationModel)
        .where(ConversationModel.uuid == c_old.uuid)
        .values(updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    )
    await db_session.execute(
        update(ConversationModel)
        .where(ConversationModel.uuid == c_new.uuid)
        .values(updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    )
    await db_session.flush()

    result = await repo.list_by_user("ord@x.com")
    assert result[0].uuid == c_new.uuid


@pytest.mark.asyncio
async def test_mode_round_trips_through_create_and_get(db_session):
    repo = ConversationRepository()
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    created = await repo.create(
        Conversation(uuid4(), "mode@x.com", "Nav", now, now, None, mode="navigate")
    )
    await db_session.flush()

    found = await repo.get_by_id(created.uuid)
    assert found is not None
    assert found.mode == "navigate"


@pytest.mark.asyncio
async def test_mode_defaults_to_none_when_omitted(db_session):
    repo = ConversationRepository()
    created = await repo.create(_conv(user_email="legacy@x.com", title="Sem modo"))
    await db_session.flush()

    found = await repo.get_by_id(created.uuid)
    assert found is not None
    assert found.mode is None
