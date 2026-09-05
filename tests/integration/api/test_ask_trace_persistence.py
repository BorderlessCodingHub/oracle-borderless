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

from tests.fakes.ag_ui_stream import events, run_input, text_of
from tests.fakes.auth import auth_headers
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
            from src.support.agent.ports import TextChunk

            yield TextChunk(text="ola ")
            raise RuntimeError("boom: engine caiu no meio do stream")

        return _stream()


def _patch_controller(monkeypatch, graph=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(
        ctrl,
        "get_turn_graph_runner",
        lambda **kw: graph or FakeTurnGraph(answer="resposta de teste"),
    )
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())


async def _fetch_trace(conversation_id: UUID) -> dict:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT question, gate_retrieve, retrieval_kept, outcome, engine_ms, "
                    "first_token_ms, tool_calls, input_tokens, output_tokens, "
                    "langsmith_run_id, error "
                    "FROM agent_traces WHERE conversation_id = :cid"
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
    """A linha do trace carrega o que o grafo de fato escreveu em `signals` —
    não só o esqueleto da Action. `FakeTurnGraph` preenche `signals` com
    valores não-triviais (2, 123, 45) para que a asserção falhe se a cadeia
    grafo → `_absorb_engine_metrics` → coluna se romper em algum ponto."""
    graph = FakeTurnGraph(
        answer="resposta de teste",
        retrieval_kept=1,
        tool_calls=2,
        input_tokens=123,
        output_tokens=45,
    )
    _patch_controller(monkeypatch, graph=graph)
    from main import app

    body = run_input("o que é o PSP?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert events(resp.text)[-1]["type"] == "RUN_FINISHED"

    trace = await _fetch_trace(UUID(body["threadId"]))
    assert trace["question"] == "o que é o PSP?"
    assert trace["outcome"] == "answer"
    assert trace["gate_retrieve"] is True
    assert trace["retrieval_kept"] == 1
    assert trace["engine_ms"] is not None
    assert trace["first_token_ms"] is not None
    assert trace["tool_calls"] == 2
    assert trace["input_tokens"] == 123
    assert trace["output_tokens"] == 45
    # ADR-0019: o runId do cliente É o run do LangSmith — um turno da tela liga
    # ao trace sem intermediário.
    assert trace["langsmith_run_id"] == body["runId"]


@pytest.mark.asyncio
async def test_failed_turn_is_traced_even_though_the_answer_is_not_persisted(monkeypatch):
    """Invariante da spec: turno que quebrou é o que mais interessa no trace."""
    _patch_controller(monkeypatch, graph=_FailingTurnGraph())
    from main import app

    body = run_input("vai falhar")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert events(resp.text)[-1]["type"] == "RUN_ERROR"

    conversation_id = UUID(body["threadId"])

    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        roles = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert roles == ["user"]  # resposta parcial não é persistida (M2)

    trace = await _fetch_trace(conversation_id)
    assert trace["outcome"] == "error"
    # Coluna informativa (correção pós-revisão): tipo + mensagem da exceção
    # real, não a string genérica devolvida ao usuário no evento SSE.
    assert trace["error"] == "RuntimeError: boom: engine caiu no meio do stream"


@pytest.mark.asyncio
async def test_refusal_leaves_engine_ms_and_first_token_ms_null(monkeypatch):
    """Correção pós-revisão: no caminho de recusa nenhum modelo roda, então
    `engine_ms`/`first_token_ms` não podem carregar o tempo de emitir uma
    string canônica — isso envenenaria a média de latência do motor que a
    página de ops mostra. Ambos devem ficar `None`."""
    _patch_controller(
        monkeypatch,
        graph=FakeTurnGraph(
            answer="Não encontrei informações sobre isso na base de conhecimento.",
            outcome="refusal",
        ),
    )
    from main import app

    body = run_input("qual a capital da Austrália?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert "Não encontrei informações sobre isso na base de conhecimento." in text_of(events(resp.text))

    trace = await _fetch_trace(UUID(body["threadId"]))
    assert trace["outcome"] == "refusal"
    assert trace["engine_ms"] is None
    assert trace["first_token_ms"] is None
