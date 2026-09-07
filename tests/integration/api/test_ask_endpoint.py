"""POST /conversations/ask fala AG-UI (ADR-0019): body RunAgentInput, resposta
`data: {json}` por evento. Usa o Postgres local, como o resto de integration/."""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes.ag_ui_stream import event_types, events, run_input, sources_of, text_of
from tests.fakes.auth import auth_headers
from tests.fakes.fake_turn_graph import FailingInPreludeTurnGraph, FailingInStreamTurnGraph, FakeTurnGraph


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


def _patch(monkeypatch, graph=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: graph or FakeTurnGraph(answer="resposta de teste"))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())


async def _roles(conversation_id: UUID, cleanup: bool = True) -> list[str]:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid ORDER BY created_at"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        if cleanup:
            await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
            await s.commit()
    return list(rows)


@pytest.mark.asyncio
async def test_ask_streams_ag_ui_events_and_persists_both_turns(monkeypatch):
    _patch(monkeypatch)
    from main import app

    body = run_input("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "event:" not in resp.text  # AG-UI: tudo em data:, sem campo event
        evs = events(resp.text)

    types = event_types(evs)
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert evs[0]["threadId"] == body["threadId"]
    assert evs[0]["runId"] == body["runId"]
    assert "STEP_STARTED" in types and "STEP_FINISHED" in types
    assert types.index("TEXT_MESSAGE_START") < types.index("TEXT_MESSAGE_CONTENT") < types.index("TEXT_MESSAGE_END")
    assert types.count("TEXT_MESSAGE_START") == 1
    assert text_of(evs) == "resposta de teste "
    assert [c["title"] for c in sources_of(evs)] == ["Doc"]
    message_ids = {e["messageId"] for e in evs if e["type"].startswith("TEXT_MESSAGE")}
    assert len(message_ids) == 1

    assert await _roles(UUID(body["threadId"])) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_ask_reuses_the_thread_id_as_the_conversation(monkeypatch):
    _patch(monkeypatch)
    from main import app

    thread_id = str(uuid4())
    headers = await auth_headers("asker@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/conversations/ask", json=run_input("primeira", thread_id), headers=headers)
        second = await client.post("/conversations/ask", json=run_input("segunda", thread_id), headers=headers)
        assert first.status_code == 200 and second.status_code == 200

    assert await _roles(UUID(thread_id)) == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_ask_with_someone_elses_thread_id_is_404(monkeypatch):
    _patch(monkeypatch)
    from main import app

    thread_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner = await client.post("/conversations/ask", json=run_input("minha"), headers=await auth_headers("owner@x.com"))
        assert owner.status_code == 200
        conversation_id = events(owner.text)[0]["threadId"]
        intruder = await client.post(
            "/conversations/ask",
            json=run_input("dele", conversation_id),
            headers=await auth_headers("intruder@x.com"),
        )
        assert intruder.status_code == 404

    assert await _roles(UUID(conversation_id)) == ["user", "assistant"]  # nada do intruso


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(threadId="not-a-uuid"),
        lambda b: b.update(runId="123"),
        lambda b: b.update(messages=[{"id": "m", "role": "assistant", "content": "x"}]),
        lambda b: b.update(messages=[{"id": "m", "role": "user", "content": "   "}]),
        lambda b: b.update(messages=[]),
    ],
)
async def test_ask_with_an_invalid_body_is_422(monkeypatch, mutate):
    _patch(monkeypatch)
    from main import app

    body = run_input("x")
    mutate(body)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_failure_emits_run_error_without_run_finished_and_does_not_persist_assistant(monkeypatch):
    _patch(monkeypatch, graph=FailingInStreamTurnGraph())
    from main import app

    body = run_input("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        evs = events(resp.text)

    types = event_types(evs)
    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types
    assert evs[-1]["message"] == "erro ao gerar a resposta"
    # o texto parcial que abriu foi fechado antes do erro
    assert types.index("TEXT_MESSAGE_END") < types.index("RUN_ERROR")
    # F2: os passos da fase 1 sobrevivem ao erro — RUN_STARTED + passos + RUN_ERROR
    assert types.index("STEP_STARTED") < types.index("RUN_ERROR")

    assert await _roles(UUID(body["threadId"])) == ["user"]


@pytest.mark.asyncio
async def test_ask_streams_refusal_with_empty_sources_and_persists_both_turns(monkeypatch):
    _patch(
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
        assert resp.status_code == 200
        evs = events(resp.text)

    assert text_of(evs) == "Não encontrei informações sobre isso na base de conhecimento. "
    assert sources_of(evs) == []
    assert event_types(evs)[-1] == "RUN_FINISHED"

    assert await _roles(UUID(body["threadId"])) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_prelude_runs_inside_its_own_session_scope_and_stream_runs_without_one(monkeypatch):
    """ADR-0020, os três escopos: a fase 1 vê uma sessão async aberta (a do
    escopo 2, não a do request — que já fechou quando o corpo começa); a fase 2
    vê None. Se `stream()` visse sessão, alguém moveu banco para o streaming."""
    from sqlalchemy.ext.asyncio import AsyncSession

    graph = FakeTurnGraph(answer="resposta de teste")
    _patch(monkeypatch, graph=graph)
    from main import app

    body = run_input("o que é o PSP?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert event_types(events(resp.text))[-1] == "RUN_FINISHED"

    assert isinstance(graph.last_run.prelude_session, AsyncSession)
    # não é a sessão do request (já fechada pelo middleware): é uma sessão viva do escopo 2
    assert graph.last_run.prelude_session.is_active
    assert graph.last_run.stream_session is None
    assert await _roles(UUID(body["threadId"])) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_a_prelude_failure_emits_run_error_after_the_steps_that_ran_and_keeps_the_question(monkeypatch):
    """D2 / spec §8: falha em gate/retrieve não é mais um 500 com rollback da
    pergunta — vira RUN_ERROR depois dos passos já emitidos, a pergunta fica
    gravada e a resposta não é persistida."""
    _patch(monkeypatch, graph=FailingInPreludeTurnGraph())
    from main import app

    body = run_input("vai quebrar no retrieve")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200  # headers já foram: o erro é no corpo
        evs = events(resp.text)

    types = event_types(evs)
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types
    assert "TEXT_MESSAGE_START" not in types
    gate_steps = [e for e in evs if e["type"] in ("STEP_STARTED", "STEP_FINISHED") and e["stepName"] == "gate"]
    assert [e["type"] for e in gate_steps] == ["STEP_STARTED", "STEP_FINISHED"]
    assert evs[-1]["message"] == "erro ao gerar a resposta"

    assert await _roles(UUID(body["threadId"])) == ["user"]
