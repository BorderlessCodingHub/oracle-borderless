from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes.fake_turn_graph import FakeTurnGraph


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


class _FailingTurnGraph:
    """Emite um token e quebra no meio do stream — para o teste de erro."""

    async def start(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        if signals is not None:
            signals.outcome = "answer"

        async def _stream():
            from src.support.agent.ports import AgentStreamChunk

            yield AgentStreamChunk(type="text", text="ola ")
            raise RuntimeError("boom: engine caiu no meio do stream")

        return _stream()


def _parse_conversation_id(body: str) -> str:
    # localiza o bloco "event: conversation" e lê o data da linha seguinte
    import json

    blocks = body.split("\n\n")
    for b in blocks:
        if "event: conversation" in b:
            data_line = next(l for l in b.split("\n") if l.startswith("data:"))
            return json.loads(data_line[5:].strip())["id"]
    raise AssertionError("evento 'conversation' não emitido")


def _concat_tokens(body: str) -> str:
    """`FakeTurnGraph` emite um `event: token` por palavra — reconstrói o texto
    completo para comparar com a frase esperada."""
    import json

    text = ""
    for b in body.split("\n\n"):
        if b.startswith("event: token"):
            data_line = next(l for l in b.split("\n") if l.startswith("data:"))
            text += json.loads(data_line[5:].strip())["text"]
    return text


@pytest.mark.asyncio
async def test_ask_streams_and_persists_both_turns(monkeypatch):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(
        ctrl, "get_turn_graph_runner", lambda **kw: FakeTurnGraph(answer="resposta de teste")
    )
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/conversations/ask",
            json={"question": "o que é o onboarding?"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "event: conversation" in body
        assert "resposta" in body
        assert "event: sources" in body
        assert "event: done" in body

    conversation_id = UUID(_parse_conversation_id(body))

    # verifica persistência num escopo de sessão próprio
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid ORDER BY created_at"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert rows == ["user", "assistant"]
        # cleanup (evita acúmulo entre execuções)
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()


@pytest.mark.asyncio
async def test_ask_failure_emits_error_and_does_not_persist_assistant(monkeypatch):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: _FailingTurnGraph())
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json={"question": "o que é o onboarding?"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: error" in body
        assert "event: done" in body

    conversation_id = UUID(_parse_conversation_id(body))
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        roles = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert "assistant" not in roles  # resposta parcial NÃO foi persistida
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()


@pytest.mark.asyncio
async def test_ask_streams_refusal_and_persists_both_turns_when_nothing_found(monkeypatch):
    """Fim a fim: o grafo decide recusa (gate + retrieval + limiar já rodaram
    dentro dele) — o SSE carrega a recusa determinística, sem tokens de motor,
    e ainda assim é persistida como qualquer resposta."""
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(
        ctrl,
        "get_turn_graph_runner",
        lambda **kw: FakeTurnGraph(
            answer="Não encontrei informações sobre isso na base de conhecimento.",
            outcome="refusal",
        ),
    )
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/conversations/ask",
            json={"question": "qual a capital da Austrália?"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = resp.text
        assert "event: conversation" in body
        assert "Não encontrei informações sobre isso na base de conhecimento." in _concat_tokens(body)
        assert 'event: sources\ndata: {"citations": []}' in body
        assert "event: done" in body

    conversation_id = UUID(_parse_conversation_id(body))

    # verifica persistência num escopo de sessão próprio
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid ORDER BY created_at"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert rows == ["user", "assistant"]  # a recusa entra na memória como qualquer resposta
        # cleanup (evita acúmulo entre execuções)
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()
