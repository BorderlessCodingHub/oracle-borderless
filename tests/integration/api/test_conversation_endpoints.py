import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes.auth import auth_headers


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    yield
    from src.support.core.database import engine

    await engine.dispose()


async def _seed_conversation(user_email: str):
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.domain.conversations.entities.conversation import Conversation
    from src.domain.conversations.entities.message import Message
    from src.domain.conversations.repositories.conversation_repository import ConversationRepository
    from src.domain.conversations.repositories.message_repository import MessageRepository
    from src.domain.shared.value_objects.citation import Citation
    from src.support.core.session_scope import run_in_async_session

    cid = uuid4()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)

    async def _work():
        await ConversationRepository().create(
            Conversation(cid, user_email, "Título da conversa", now, now, None)
        )
        from uuid6 import uuid7

        await MessageRepository().append(
            Message(uuid7(), cid, "user", "pergunta", now)
        )
        await MessageRepository().append(
            Message(
                uuid7(), cid, "assistant", "resposta", now,
                sources=[Citation("notion", "Doc", "https://n", "s", "pid")],
            )
        )

    await run_in_async_session(_work)
    return cid


@pytest.mark.asyncio
async def test_list_and_get_conversation():
    email = "lister@x.com"
    cid = await _seed_conversation(email)
    other_cid = await _seed_conversation("someoneelse@x.com")
    from main import app

    transport = ASGITransport(app=app)
    headers = auth_headers(email)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/conversations", headers=headers)
        assert listing.status_code == 200
        ids = [c["id"] for c in listing.json()]
        assert str(cid) in ids
        # Cross-user filtering: outra pessoa não pode aparecer na minha listagem.
        assert str(other_cid) not in ids

        detail = await client.get(f"/conversations/{cid}", headers=headers)
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["title"] == "Título da conversa"
        assert [m["role"] for m in payload["messages"]] == ["user", "assistant"]
        assert payload["messages"][1]["sources"][0]["title"] == "Doc"

    # cleanup
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(
            text("DELETE FROM conversations WHERE uuid IN (:cid, :other_cid)"),
            {"cid": cid, "other_cid": other_cid},
        )
        await s.commit()


@pytest.mark.asyncio
async def test_get_missing_conversation_returns_404():
    from uuid import uuid4

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/conversations/{uuid4()}", headers=auth_headers("qualquer@x.com"))
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sem_token_tudo_da_401():
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/conversations")).status_code == 401
        assert (
            await client.post("/conversations/ask", json={"question": "q", "conversation_id": None})
        ).status_code == 401


@pytest.mark.asyncio
async def test_conversa_de_outro_usuario_da_404():
    cid = await _seed_conversation("dona@x.com")
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/conversations/{cid}", headers=auth_headers("intrusa@x.com"))
        assert resp.status_code == 404

    # cleanup
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": cid})
        await s.commit()
