"""Task 4 — entitlement fail-closed do modo mentor em POST /conversations/ask.

Usa o Postgres local, como o resto de integration/ (ver tests/integration/api/
test_ask_endpoint.py). ESCRITO MAS NÃO EXECUTADO nesta tarefa: sem Postgres
disponível no ambiente onde a Task 4 foi implementada — `uv run pytest
tests/integration/api/test_ask_mentor_entitlement.py -v` fica pendente de
rodar com o banco local de pé (ver docs/testing-guide.md / e2e-local-run).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.session_scope import run_in_async_session
from tests.fakes.auth import auth_headers
from tests.fakes.fake_turn_graph import FakeTurnGraph
from tests.fakes.stream_events import ask_body


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


def _patch(monkeypatch, graph=None, has_access: bool | Exception = True):
    import src.app.api.controllers.conversation_controller as ctrl
    from src.support.clients.borderless.borderless_lesson_access_client import (
        BorderlessLessonAccessClient,
    )
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    graph = graph or FakeTurnGraph(answer="resposta do mentor")
    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: graph.with_config(**kw))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())

    async def _fake_has_access(self, bearer, program_slug, module_slug, video_slug):
        if isinstance(has_access, Exception):
            raise has_access
        return has_access

    monkeypatch.setattr(BorderlessLessonAccessClient, "has_access", _fake_has_access)
    return graph


@pytest.mark.asyncio
async def test_mentor_without_lesson_id_is_400(monkeypatch):
    _patch(monkeypatch)
    from main import app

    body = ask_body("o que é um token?", mode="mentor")  # sem lesson_id
    headers = await auth_headers("mentor-sem-id@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mentor_with_denied_access_is_403_and_the_graph_never_runs(monkeypatch):
    lesson = await _seed_lesson("v-negado")
    graph = _patch(monkeypatch, has_access=False)
    from main import app

    body = ask_body("o que é um token?", mode="mentor", lesson_id=lesson.platform_video_id)
    headers = await auth_headers("mentor-negado@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 403

    assert graph.received_mode is None  # run() nunca foi chamado


@pytest.mark.asyncio
async def test_mentor_with_an_unindexed_lesson_is_403(monkeypatch):
    """Fail-closed: um platform_video_id que a ingestão nunca viu nega, não crasha."""
    graph = _patch(monkeypatch, has_access=True)
    from main import app

    body = ask_body("o que é um token?", mode="mentor", lesson_id="video-fantasma")
    headers = await auth_headers("mentor-fantasma@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 403

    assert graph.received_mode is None


@pytest.mark.asyncio
async def test_mentor_with_access_reaches_the_runner_with_mode_lesson_id_and_extra_config(monkeypatch):
    lesson = await _seed_lesson("v-liberado")
    graph = _patch(monkeypatch, has_access=True)
    from main import app

    body = ask_body("o que é um token?", mode="mentor", lesson_id=lesson.platform_video_id)
    headers = await auth_headers("mentor-liberado@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=headers)
        assert resp.status_code == 200

    assert graph.received_mode == "mentor"
    # C1: o STATE recebe o id da PLATFORM, não o uuid interno.
    assert graph.received_lesson_id == lesson.platform_video_id

    config = graph.received_extra_config
    assert set(config) >= {
        "lesson_id", "lesson_distances", "question_embedding",
        "lesson_platform_video_id", "lesson_program_slug",
    }
    # C1: o escopo da tool (extra_config["lesson_id"]) é o uuid INTERNO.
    assert config["lesson_id"] == lesson.uuid
    assert config["lesson_id"] != config["lesson_platform_video_id"]
    assert config["lesson_platform_video_id"] == lesson.platform_video_id
    assert config["lesson_program_slug"] == lesson.program_slug
    # C5: as listas pré-semeadas nascem vazias — a tool as preenche em place.
    assert config["lesson_distances"] == []
    assert config["question_embedding"] == []
