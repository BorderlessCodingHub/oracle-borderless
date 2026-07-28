from typing import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


class FailingOracleEngine:
    async def stream_answer(self, question, history, knowledge=None) -> AsyncIterator:
        from src.support.agent.ports import AgentStreamChunk

        yield AgentStreamChunk(type="text", text="ola ")
        raise RuntimeError("boom: engine caiu no meio do stream")


class _FakeSearchAction:
    """Substitui `SearchKnowledgeBaseAction` real: devolve 1 trecho não-vazio,
    para que `retrieve=True` chegue de fato ao engine (sem isso a busca real
    contra a base de teste, sem documentos no escopo, sempre voltava vazia —
    o que agora aciona a recusa em vez do engine)."""

    def __init__(self, *a, **kw):
        pass

    async def execute(self, query, top_k=None):
        from src.domain.shared.value_objects.citation import Citation
        from src.support.agent.ports import KnowledgeSnippet

        return [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "s", "pid"))]


class _EmptySearchAction:
    """Substitui `SearchKnowledgeBaseAction` real por uma busca que sempre volta
    vazia — para testar deliberadamente o caminho de recusa (`retrieve=True` +
    nada encontrado), fim a fim, via HTTP."""

    def __init__(self, *a, **kw):
        pass

    async def execute(self, query, top_k=None):
        return []


def _parse_conversation_id(body: str) -> str:
    # localiza o bloco "event: conversation" e lê o data da linha seguinte
    import json

    blocks = body.split("\n\n")
    for b in blocks:
        if "event: conversation" in b:
            data_line = next(l for l in b.split("\n") if l.startswith("data:"))
            return json.loads(data_line[5:].strip())["id"]
    raise AssertionError("evento 'conversation' não emitido")


@pytest.mark.asyncio
async def test_ask_streams_and_persists_both_turns(monkeypatch):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
    from tests.fakes.fake_oracle_engine import FakeOracleEngine
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(ctrl, "get_oracle_engine", lambda: FakeOracleEngine(answer="resposta de teste"))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
    monkeypatch.setattr(ctrl, "SearchKnowledgeBaseAction", _FakeSearchAction)

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
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(ctrl, "get_oracle_engine", lambda: FailingOracleEngine())
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
    monkeypatch.setattr(ctrl, "SearchKnowledgeBaseAction", _FakeSearchAction)

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
    """Fim a fim: gate pede busca, busca não acha nada — recusa determinística
    pela SSE, sem chamar o engine, e ainda assim persistida como qualquer resposta."""
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
    from tests.fakes.fake_oracle_engine import FakeOracleEngine
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(ctrl, "get_oracle_engine", lambda: FakeOracleEngine(answer="resposta de teste"))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
    monkeypatch.setattr(ctrl, "SearchKnowledgeBaseAction", _EmptySearchAction)

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
        assert "Não encontrei informações sobre isso na base de conhecimento." in body
        assert 'event: sources\ndata: {"citations": []}' in body
        assert "event: done" in body
        assert "resposta de teste" not in body  # o engine nunca foi chamado

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
