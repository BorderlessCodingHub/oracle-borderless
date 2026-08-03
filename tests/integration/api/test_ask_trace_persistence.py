"""Depois do stream, o turno tem que estar em agent_traces.

Segue o padrão de `test_ask_endpoint.py`: monkeypatcha as factories do
controller, bate no app via ASGITransport e verifica num escopo de sessão
próprio — os testes de API usam o banco de **dev** (o app resolve
`settings.database_url_async`), não o de teste. Cada teste limpa o que criou.
"""

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


class _FakeSearchAction:
    def __init__(self, *a, **kw):
        pass

    async def execute(self, query, top_k=None):
        from src.domain.shared.value_objects.citation import Citation
        from src.support.agent.ports import KnowledgeSnippet

        return [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "s", "pid"))]


class _FailingEngine:
    async def stream_answer(self, question, history, knowledge=None, metrics=None):
        from src.support.agent.ports import AgentStreamChunk

        yield AgentStreamChunk(type="text", text="ola ")
        raise RuntimeError("boom: engine caiu no meio do stream")


def _parse_conversation_id(body: str) -> str:
    import json

    for block in body.split("\n\n"):
        if "event: conversation" in block:
            data_line = next(l for l in block.split("\n") if l.startswith("data:"))
            return json.loads(data_line[5:].strip())["id"]
    raise AssertionError("evento 'conversation' não emitido")


def _patch_controller(monkeypatch, engine=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
    from tests.fakes.fake_oracle_engine import FakeOracleEngine
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(
        ctrl, "get_oracle_engine", lambda: engine or FakeOracleEngine(answer="resposta de teste")
    )
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
    monkeypatch.setattr(ctrl, "SearchKnowledgeBaseAction", _FakeSearchAction)


async def _fetch_trace(conversation_id: UUID) -> dict:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT question, gate_retrieve, retrieval_kept, outcome, engine_ms, "
                    "first_token_ms, events, error FROM agent_traces "
                    "WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            )
        ).mappings().all()
        await s.execute(
            text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id}
        )
        await s.commit()
    assert len(row) == 1, f"esperava 1 trace, achei {len(row)}"
    return dict(row[0])


@pytest.mark.asyncio
async def test_trace_row_exists_after_a_successful_ask(monkeypatch):
    _patch_controller(monkeypatch)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json={"question": "o que é o PSP?"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: done" in body

    trace = await _fetch_trace(UUID(_parse_conversation_id(body)))
    assert trace["question"] == "o que é o PSP?"
    assert trace["outcome"] == "answer"
    assert trace["gate_retrieve"] is True
    assert trace["retrieval_kept"] == 1
    assert trace["engine_ms"] is not None
    assert trace["first_token_ms"] is not None
    assert trace["events"][0]["step"] == "turn_start"
    assert trace["events"][-1]["step"] == "turn_end"


@pytest.mark.asyncio
async def test_failed_turn_is_traced_even_though_the_answer_is_not_persisted(monkeypatch):
    """Invariante da spec: turno que quebrou é o que mais interessa no trace."""
    _patch_controller(monkeypatch, engine=_FailingEngine())
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json={"question": "vai falhar"})
        body = resp.text
        assert "event: error" in body

    conversation_id = UUID(_parse_conversation_id(body))

    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        roles = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert "assistant" not in roles  # resposta parcial não é persistida (M2)

    trace = await _fetch_trace(conversation_id)
    assert trace["outcome"] == "error"
    assert trace["error"]
