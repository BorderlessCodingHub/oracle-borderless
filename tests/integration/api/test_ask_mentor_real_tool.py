"""C1 (ruling C6) fim a fim: um turno mentor de verdade, grafo real, ToolNode
real, `search_lesson` real — a única coisa fake é o modelo de chat (que emite
UMA tool call de `search_lesson` e depois a frase final) e o embeddings client
(determinístico, sem custo de rede).

Ao contrário de `test_ask_mentor_entitlement.py`/`test_mentor_trace_persistence.py`
(que trocam o grafo inteiro por `FakeTurnGraph`), este teste deixa o
`TurnGraphRunner`/`TURN_GRAPH` reais rodarem — é o único jeito de provar que a
tool `search_lesson` sobrevive à passagem de `stream()` sem sessão (ADR-0020) e
ainda assim entrega uma citação `source_type == "lesson"` até a mensagem do
assistente persistida.

ESCRITO MAS NÃO EXECUTADO (ruling B2): sem Postgres disponível neste ambiente,
validado só com `uv run pytest tests/integration --collect-only -q`.
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy import text

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.session_scope import run_in_async_session
from tests.fakes.auth import auth_headers
from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
from tests.fakes.stream_events import ask_body

QUESTION = "o que é um token?"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


async def _seed_lesson_with_chunk(video_id: str) -> Lesson:
    """Uma aula com UM chunk cujo embedding é EXATAMENTE o que
    `FakeEmbeddingsClient` calcula para `QUESTION` — a busca acha o trecho de
    propósito, não por sorte de vizinho mais próximo."""

    async def _work():
        lesson = await LessonRepository().upsert_from_catalog(
            Lesson(
                uuid=uuid4(), platform_video_id=video_id, program_slug="base",
                module_slug="m1", video_slug="aula-1", title="Tokens e embeddings",
                provider="PANDA_VIDEO", provider_ref="ref-1",
            )
        )
        vector = FakeEmbeddingsClient()._vector(QUESTION)
        await LessonChunkRepository().replace_for_lesson(lesson.uuid, [
            LessonChunk(
                uuid=uuid4(), lesson_id=lesson.uuid, ordinal=0,
                content="Um token é a menor unidade que o modelo processa.",
                start_seconds=12.0, end_seconds=20.0, embedding=vector,
            )
        ])
        return lesson

    return await run_in_async_session(_work)


class _FakeMentorChatModel:
    """Modelo fake do turno mentor: primeira chamada pede `search_lesson`,
    segunda devolve a resposta final. `bind_tools` devolve `self` — o grafo
    real ainda assim decide o roteamento pelas tool_calls da mensagem."""

    def __init__(self) -> None:
        self.call_count = 0
        self.bound_tool_names: list[str] = []

    def bind_tools(self, tools):
        self.bound_tool_names = [t.name for t in tools]
        return self

    async def ainvoke(self, messages):
        self.call_count += 1
        if self.call_count == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_lesson", "args": {"query": QUESTION}, "id": "call-1"}
                ],
            )
        return AIMessage(content="Um token é a unidade que o modelo processa.")


def _patch(monkeypatch):
    import src.app.api.controllers.conversation_controller as ctrl
    import src.support.agent.graph.nodes as nodes_module
    from src.support.clients.borderless.borderless_lesson_access_client import (
        BorderlessLessonAccessClient,
    )

    model = _FakeMentorChatModel()
    monkeypatch.setattr(nodes_module, "build_chat_model", lambda: model)

    # Deliberadamente NÃO monkeypatcha `ctrl.get_turn_graph_runner`: este teste
    # quer o TurnGraphRunner/TURN_GRAPH DE VERDADE (grafo, ToolNode, tool
    # `search_lesson` reais) — é o que exercita o fix do C1.
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(
        "src.support.clients.embeddings.embeddings_client.get_embeddings_client",
        lambda: FakeEmbeddingsClient(),
    )

    async def _fake_has_access(self, bearer, program_slug, module_slug, video_slug):
        return True

    monkeypatch.setattr(BorderlessLessonAccessClient, "has_access", _fake_has_access)
    return model


async def _fetch_assistant_sources(conversation_id: UUID) -> list[dict]:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT sources FROM messages WHERE conversation_id = :cid "
                    "AND role = 'assistant'"
                ),
                {"cid": conversation_id},
            )
        ).mappings().one()
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()
    return row["sources"] or []


@pytest.mark.asyncio
async def test_a_real_mentor_turn_with_the_real_graph_and_tool_reaches_a_lesson_citation(
    monkeypatch,
):
    lesson = await _seed_lesson_with_chunk("v-real-tool")
    model = _patch(monkeypatch)
    from main import app

    body = ask_body(QUESTION, mode="mentor", lesson_id=lesson.platform_video_id)
    headers = await auth_headers("mentor-real-tool@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 200

    # o modelo foi chamado duas vezes: pediu a busca, depois respondeu de fato.
    assert model.call_count == 2
    assert model.bound_tool_names == ["search_lesson"]

    conversation_id = UUID(body["config"]["configurable"]["thread_id"])
    sources = await _fetch_assistant_sources(conversation_id)

    assert len(sources) == 1
    assert sources[0]["source_type"] == "lesson"
    assert "Tokens e embeddings" in sources[0]["title"]
