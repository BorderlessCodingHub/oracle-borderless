"""POST /conversations/ask entrega StreamEvents (ADR-0021): body {input, config},
resposta `event: <nome>\\ndata: {json}` por bloco. Usa o Postgres local, como o
resto de integration/."""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes.auth import auth_headers
from tests.fakes.fake_turn_graph import FailingInPreludeTurnGraph, FailingInStreamTurnGraph, FakeTurnGraph
from tests.fakes.stream_events import (
    ask_body,
    event_names,
    events,
    is_root,
    navigation_of,
    root_end,
    sources_of,
    steps,
    text_of,
)

# Shape público de `NavigationResult.to_public()` (borderless_navigation_client.py):
# o que o nó `navigate` real escreve em `state["navigation"]`.
RESULT_PUBLIC = {
    "destination": {"id": "code-breakers", "path": "/code-breakers", "labelKey": "nav.codeBreakers", "label": "Code Breakers"},
    "access": "allowed",
    "unlock": None,
    "signals": {"matchedTags": ["algorithms"], "inProgress": False, "difficulty": "medium", "fallback": False},
    "alternatives": [],
}

_FAKE_CATALOG_TEXT = "- code-breakers (hub): pratique algoritmos em desafios"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


def _patch(monkeypatch, graph=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    graph = graph or FakeTurnGraph(answer="resposta de teste")
    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: graph.with_config(**kw))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    # NavigationCatalog().describe() faz HTTP real contra BORDERLESS_AUTH_URL —
    # inalcançável/fake no ambiente de teste. Determinístico e offline: um
    # texto fixo no lugar da chamada de rede (a Action que consome o catálogo
    # real já tem cobertura própria).
    async def _fake_describe(self, access_token):
        return _FAKE_CATALOG_TEXT

    monkeypatch.setattr(ctrl.NavigationCatalog, "describe", _fake_describe)


def _thread(body: dict) -> str:
    return body["config"]["configurable"]["thread_id"]


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
async def test_ask_streams_stream_events_and_persists_both_turns(monkeypatch):
    _patch(monkeypatch)
    from main import app

    body = ask_body("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        evs = events(resp.text)  # afirma event: == data.event e os sete campos

    names = event_names(evs)
    assert names[0] == "on_chain_start" and is_root(evs[0])
    assert evs[0]["metadata"]["thread_id"] == _thread(body)
    assert evs[0]["run_id"] == body["config"]["run_id"]
    assert names[-1] == "on_chain_end" and is_root(evs[-1])
    assert steps(evs) == [("gate", "start"), ("gate", "end"), ("retrieve", "start"), ("retrieve", "end"), ("answer", "start"), ("answer", "end")]
    assert "on_chat_model_stream" in names
    assert text_of(evs) == "resposta de teste "
    assert [c["title"] for c in sources_of(evs)] == ["Doc"]
    assert all("page_id" not in c for c in sources_of(evs))
    # decisão 2 da spec: os dois modos saem no fio
    modes = [e["data"]["chunk"][0] for e in evs if e["event"] == "on_chain_stream" and is_root(e)]
    assert "updates" in modes and "values" in modes

    assert await _roles(UUID(_thread(body))) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_ask_reuses_the_thread_id_as_the_conversation(monkeypatch):
    _patch(monkeypatch)
    from main import app

    thread_id = str(uuid4())
    headers = await auth_headers("asker@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/conversations/ask", json=ask_body("primeira", thread_id), headers=headers)
        second = await client.post("/conversations/ask", json=ask_body("segunda", thread_id), headers=headers)
        assert first.status_code == 200 and second.status_code == 200

    assert await _roles(UUID(thread_id)) == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_ask_with_someone_elses_thread_id_is_404(monkeypatch):
    _patch(monkeypatch)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner_body = ask_body("minha")
        owner = await client.post("/conversations/ask", json=owner_body, headers=await auth_headers("owner@x.com"))
        assert owner.status_code == 200
        conversation_id = events(owner.text)[0]["metadata"]["thread_id"]
        assert conversation_id == _thread(owner_body)
        intruder = await client.post(
            "/conversations/ask",
            json=ask_body("dele", conversation_id),
            headers=await auth_headers("intruder@x.com"),
        )
        assert intruder.status_code == 404

    assert await _roles(UUID(conversation_id)) == ["user", "assistant"]  # nada do intruso


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["config"]["configurable"].update(thread_id="not-a-uuid"),
        lambda b: b["config"].update(run_id="123"),
        lambda b: b["input"].update(question="   "),
        lambda b: b.pop("config"),
        lambda b: b.pop("input"),
    ],
)
async def test_ask_with_an_invalid_body_is_422(monkeypatch, mutate):
    _patch(monkeypatch)
    from main import app

    body = ask_body("x")
    mutate(body)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_failure_emits_on_chain_error_without_root_end_and_does_not_persist_assistant(monkeypatch):
    _patch(monkeypatch, graph=FailingInStreamTurnGraph())
    from main import app

    body = ask_body("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        evs = events(resp.text)

    names = event_names(evs)
    assert names[-1] == "on_chain_error" and is_root(evs[-1])
    assert evs[-1]["data"] == {"error": "erro ao gerar a resposta"}
    assert evs[-1]["metadata"]["thread_id"] == _thread(body)
    assert not any(e["event"] == "on_chain_end" and is_root(e) for e in evs)
    # os passos da fase 1 e o token que saiu sobrevivem ao erro
    assert ("gate", "end") in steps(evs)
    assert text_of(evs) == "ola "

    assert await _roles(UUID(_thread(body))) == ["user"]


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

    body = ask_body("qual a capital da Austrália?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        evs = events(resp.text)

    assert ("refuse", "start") in steps(evs) and ("refuse", "end") in steps(evs)
    assert "on_chat_model_stream" not in event_names(evs)
    assert text_of(evs) == "Não encontrei informações sobre isso na base de conhecimento. "
    assert sources_of(evs) == []
    assert root_end(evs)["data"]["output"]["outcome"] == "refusal"

    assert await _roles(UUID(_thread(body))) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_prelude_runs_inside_its_own_session_scope_and_stream_runs_without_one(monkeypatch):
    """ADR-0020, os três escopos: a fase 1 vê uma sessão async aberta (a do
    escopo 2, não a do request — que já fechou quando o corpo começa); a fase 2
    vê None. Se `stream()` visse sessão, alguém moveu banco para o streaming."""
    from sqlalchemy.ext.asyncio import AsyncSession

    graph = FakeTurnGraph(answer="resposta de teste")
    _patch(monkeypatch, graph=graph)
    from main import app

    body = ask_body("o que é o PSP?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert is_root(events(resp.text)[-1])

    assert isinstance(graph.last_run.prelude_session, AsyncSession)
    assert graph.last_run.prelude_session.is_active
    assert graph.last_run.stream_session is None
    assert await _roles(UUID(_thread(body))) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_a_prelude_failure_emits_on_chain_error_after_the_steps_that_ran_and_keeps_the_question(monkeypatch):
    """Falha em gate/retrieve vira on_chain_error depois dos passos já emitidos,
    a pergunta fica gravada e a resposta não é persistida (ADR-0020, D2)."""
    _patch(monkeypatch, graph=FailingInPreludeTurnGraph())
    from main import app

    body = ask_body("vai quebrar no retrieve")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200  # headers já foram: o erro é no corpo
        evs = events(resp.text)

    names = event_names(evs)
    assert names[0] == "on_chain_start" and is_root(evs[0])
    assert names[-1] == "on_chain_error"
    assert not any(e["event"] == "on_chain_end" and is_root(e) for e in evs)
    assert "on_chat_model_stream" not in names
    assert steps(evs) == [("gate", "start"), ("gate", "end"), ("retrieve", "start")]

    assert await _roles(UUID(_thread(body))) == ["user"]


async def _get_conversation(client: AsyncClient, conversation_id: str, headers: dict) -> dict:
    resp = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_ask_in_navigate_mode_streams_the_destination_before_any_answer_token_and_persists_it(monkeypatch):
    """Task 9: o controller leva token/perfil/catálogo ao grafo (extra_config) e
    captura `navigation_of` — o destino chega ANTES da frase final (spec §5.3)
    e é persistido na mensagem do assistente."""
    graph = FakeTurnGraph(answer="Vamos praticar!", navigation=RESULT_PUBLIC)
    _patch(monkeypatch, graph=graph)
    from main import app

    body = ask_body("quero praticar algoritmos", mode="navigate", locale="en")
    headers = await auth_headers("navigator@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 200
        evs = events(resp.text)

        nav = navigation_of(evs)
        assert nav is not None
        assert nav["destination"]["path"] == "/code-breakers"
        assert nav["access"] == "allowed"

        # O destino chega no chunk `updates` ANTES do primeiro token do modelo.
        nav_index = next(
            i
            for i, e in enumerate(evs)
            if e["event"] == "on_chain_stream"
            and is_root(e)
            and e["data"]["chunk"][0] == "updates"
            and "navigate" in e["data"]["chunk"][1]
        )
        first_token_index = next(i for i, e in enumerate(evs) if e["event"] == "on_chat_model_stream")
        assert nav_index < first_token_index

        assert root_end(evs)["data"]["output"]["navigation"] == nav

        detail = await _get_conversation(client, _thread(body), headers)

    assert detail["messages"][-1]["role"] == "assistant"
    assert detail["messages"][-1]["navigation"] == RESULT_PUBLIC

    assert graph.received_mode == "navigate"
    assert graph.received_locale == "en"
    assert graph.received_extra_config["platform_token"] == "plat-token-teste"
    assert set(graph.received_extra_config["user_profile"]) == {"membership", "seniority", "careerStage"}
    assert graph.received_extra_config["navigation_catalog_text"] == _FAKE_CATALOG_TEXT

    await _roles(UUID(_thread(body)))  # limpa a conversa criada


@pytest.mark.asyncio
async def test_ask_with_default_body_keeps_navigation_none(monkeypatch):
    graph = FakeTurnGraph(answer="resposta de teste")
    _patch(monkeypatch, graph=graph)
    from main import app

    body = ask_body("o que é o onboarding?")
    headers = await auth_headers("asker2@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 200
        evs = events(resp.text)
        assert navigation_of(evs) is None
        assert root_end(evs)["data"]["output"].get("navigation") is None

        detail = await _get_conversation(client, _thread(body), headers)

    assert detail["messages"][-1]["navigation"] is None
    assert graph.received_mode == "chat"

    await _roles(UUID(_thread(body)))  # limpa a conversa criada


@pytest.mark.asyncio
async def test_ask_falls_back_to_the_embedded_snapshot_when_the_catalog_is_unavailable(monkeypatch):
    """Um catálogo indisponível (API fora, token recusado, etc.) nunca pode
    derrubar o turno — o controller cai para `NavigationCatalog.snapshot_text()`."""
    import src.app.api.controllers.conversation_controller as ctrl
    from src.support.agent.navigation_catalog import NavigationCatalog

    graph = FakeTurnGraph(answer="resposta de teste")
    _patch(monkeypatch, graph=graph)

    async def _raising_describe(self, access_token):
        raise RuntimeError("catálogo fora do ar")

    monkeypatch.setattr(ctrl.NavigationCatalog, "describe", _raising_describe)

    from main import app

    body = ask_body("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker3@x.com"))
        assert resp.status_code == 200
        evs = events(resp.text)
        assert root_end(evs) is not None  # o turno seguiu apesar da falha do catálogo

    assert graph.received_extra_config["navigation_catalog_text"] == NavigationCatalog.snapshot_text()

    await _roles(UUID(_thread(body)))  # limpa a conversa criada
