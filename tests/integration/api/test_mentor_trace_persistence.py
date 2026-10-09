"""Depois do stream, um turno de mentor tem que estar em agent_traces com os
quatro campos do Task 5 (intent, lesson_id, lesson_coverage, question_embedding).

Espelha tests/integration/api/test_ask_trace_persistence.py — mesma montagem
(monkeypatcha as factories do controller, bate no app via ASGITransport,
verifica num escopo de sessão próprio).
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.session_scope import run_in_async_session
from src.support.core.settings import settings
from tests.fakes.auth import auth_headers
from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
from tests.fakes.fake_turn_graph import FakeTurnGraph
from tests.fakes.stream_events import ask_body, events, is_root


def _question_embedding(seed: str) -> list[float]:
    """Um vetor com as `settings.EMBEDDING_DIM` dimensões que a coluna
    `agent_traces.question_embedding` declara. Vetores de brinquedo (3 casas)
    fazem o pgvector recusar o INSERT — o trace some e o teste vira um
    'esperava 1 trace, achei 0' sem explicação."""
    return FakeEmbeddingsClient(dim=settings.EMBEDDING_DIM)._vector(seed)


def _dimensions(stored) -> int:
    """Casas do vetor gravado. No SELECT cru o pgvector volta como texto (esta
    conexão não registra o codec), então contar as casas é o que prova que o
    embedding chegou inteiro à coluna."""
    if isinstance(stored, str):
        return len(stored.strip("[]").split(","))
    return len(stored)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


def _catalog_lesson(video_id: str, program_slug: str = "base") -> Lesson:
    return Lesson(
        uuid=uuid4(), platform_video_id=video_id, program_slug=program_slug,
        module_slug="modulo-1", video_slug="aula-1", title="Tokens",
        provider="PANDA_VIDEO", provider_ref="ref-1",
    )


async def _seed_lesson(video_id: str, program_slug: str = "base") -> Lesson:
    async def _work():
        return await LessonRepository().upsert_from_catalog(_catalog_lesson(video_id, program_slug))

    return await run_in_async_session(_work)


def _patch(monkeypatch, graph):
    import src.app.api.controllers.conversation_controller as ctrl
    from src.support.clients.borderless.borderless_lesson_access_client import (
        BorderlessLessonAccessClient,
    )

    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: graph.with_config(**kw))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    async def _fake_has_access(self, bearer, program_slug, module_slug, video_slug):
        return True

    monkeypatch.setattr(BorderlessLessonAccessClient, "has_access", _fake_has_access)


async def _fetch_trace(conversation_id: UUID) -> dict:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT question, outcome, intent, lesson_id, program_slug, "
                    "lesson_coverage, retrieval_ran, retrieval_kept, retrieval_best_distance, "
                    "question_embedding FROM agent_traces WHERE conversation_id = :cid"
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
async def test_a_mentor_turn_records_intent_lesson_and_coverage(monkeypatch):
    """Distância mínima 0.10 (bem abaixo de MENTOR_COVERAGE_NEAR=0.35) -> 'covered'."""
    lesson = await _seed_lesson("v-trace-covered")
    graph = FakeTurnGraph(
        answer="é o Personal Study Plan",
        mentor_distances=[0.10, 0.40],
        mentor_embedding=_question_embedding("o que é o PSP?"),
    )
    _patch(monkeypatch, graph)
    from main import app

    body = ask_body("o que é o PSP?", mode="mentor", lesson_id=lesson.platform_video_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("mentor-trace@x.com"))
        assert resp.status_code == 200
        last = events(resp.text)[-1]
        assert last["event"] == "on_chain_end" and is_root(last)

    trace = await _fetch_trace(UUID(body["config"]["configurable"]["thread_id"]))
    assert trace["intent"] == "mentor"
    assert trace["lesson_id"] == lesson.platform_video_id
    assert trace["program_slug"] == lesson.program_slug
    assert trace["retrieval_ran"] is True
    assert trace["retrieval_kept"] == 2
    assert trace["retrieval_best_distance"] == 0.10
    assert trace["lesson_coverage"] == "covered"
    # O embedding que a tool calculou chega inteiro à coluna — não basta "não é
    # nulo": um vetor de dimensão errada nem seria aceito pelo pgvector.
    assert trace["question_embedding"] is not None
    assert _dimensions(trace["question_embedding"]) == settings.EMBEDDING_DIM


@pytest.mark.asyncio
async def test_a_mentor_turn_with_a_far_distance_is_a_content_gap(monkeypatch):
    lesson = await _seed_lesson("v-trace-gap")
    graph = FakeTurnGraph(
        answer="não encontrei isso na aula",
        mentor_distances=[0.90],
        mentor_embedding=_question_embedding("qual a receita de bolo?"),
    )
    _patch(monkeypatch, graph)
    from main import app

    body = ask_body("qual a receita de bolo?", mode="mentor", lesson_id=lesson.platform_video_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("mentor-gap@x.com"))
        assert resp.status_code == 200

    trace = await _fetch_trace(UUID(body["config"]["configurable"]["thread_id"]))
    assert trace["lesson_coverage"] == "gap"
    assert trace["retrieval_best_distance"] == 0.90


@pytest.mark.asyncio
async def test_a_trace_recording_failure_still_lets_the_mentor_turn_answer(monkeypatch):
    """ADR-0013 aplicado ao turno mentor: a gravação do trace pode quebrar (o
    call site está sob try/except que loga e engole) e a resposta do oráculo
    ainda assim é persistida e devolvida ao cliente."""
    lesson = await _seed_lesson("v-trace-raise")
    graph = FakeTurnGraph(
        answer="resposta apesar do trace quebrar",
        mentor_distances=[0.20],
        mentor_embedding=_question_embedding("o que é o PSP?"),
    )
    _patch(monkeypatch, graph)

    from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction

    async def _raise(self, conversation_id, draft):
        raise RuntimeError("boom: coluna estourou")

    monkeypatch.setattr(RecordTurnTraceAction, "execute", _raise)

    from main import app

    body = ask_body("o que é o PSP?", mode="mentor", lesson_id=lesson.platform_video_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("mentor-raise@x.com"))
        assert resp.status_code == 200
        last = events(resp.text)[-1]
        assert last["event"] == "on_chain_end" and is_root(last)
    conversation_id = UUID(body["config"]["configurable"]["thread_id"])

    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT content FROM messages WHERE conversation_id = :cid AND role = 'assistant'"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        # Nenhuma linha de trace foi gravada (RecordTurnTraceAction quebrou),
        # mas a resposta do assistente sobreviveu.
        trace_rows = (
            await s.execute(
                text("SELECT 1 FROM agent_traces WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).all()
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()

    # `FakeTurnRun.stream()` emite cada token como `token + " "`, então o
    # conteúdo persistido termina com um espaço; o que importa é o texto.
    assert [r.strip() for r in rows] == ["resposta apesar do trace quebrar"]
    assert trace_rows == []


@pytest.mark.asyncio
async def test_a_trace_rejected_by_the_database_does_not_cost_the_assistant_message(monkeypatch):
    """Ruling C9: o irmão acima quebra ANTES do banco (a Action levanta). Aqui a
    falha é a de verdade — um `flush()` recusado pelo Postgres DENTRO do
    savepoint do trace (embedding com dimensão errada). É o caso que
    `_persist_turn` promete aguentar: um erro de banco aborta só o savepoint
    dele, e a resposta do assistente, que vai num savepoint próprio depois,
    ainda tem que ser gravada.
    """
    lesson = await _seed_lesson("v-trace-rejected")
    graph = FakeTurnGraph(
        answer="resposta apesar do insert recusado",
        mentor_distances=[0.20],
        # DE PROPÓSITO fora da dimensão da coluna: é o que faz o pgvector
        # recusar o INSERT e o flush estourar dentro do `begin_nested`.
        mentor_embedding=[0.1, 0.2, 0.3],
    )
    _patch(monkeypatch, graph)
    from main import app

    body = ask_body("o que é o PSP?", mode="mentor", lesson_id=lesson.platform_video_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("mentor-rejected@x.com"))
        assert resp.status_code == 200
        last = events(resp.text)[-1]
        assert last["event"] == "on_chain_end" and is_root(last)
    conversation_id = UUID(body["config"]["configurable"]["thread_id"])

    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT content FROM messages WHERE conversation_id = :cid AND role = 'assistant'"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        trace_rows = (
            await s.execute(
                text("SELECT 1 FROM agent_traces WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).all()
        await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
        await s.commit()

    assert trace_rows == []
    assert [r.strip() for r in rows] == ["resposta apesar do insert recusado"]
