"""Task 6 — GET /lessons/{platform_video_id}/status.

Usa o Postgres local, como o resto de integration/ (ver tests/integration/api/
test_ask_endpoint.py). ESCRITO MAS NÃO EXECUTADO nesta tarefa: sem Postgres
disponível no ambiente onde a Task 6 foi implementada — `uv run pytest
tests/integration/api/test_lesson_status_endpoint.py -v` fica pendente de
rodar com o banco local de pé (ver docs/testing-guide.md / e2e-local-run).
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.session_scope import run_in_async_session
from tests.fakes.auth import auth_headers


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


def _lesson(video_id: str, status: TranscriptStatus = TranscriptStatus.PENDING) -> Lesson:
    return Lesson(
        uuid=uuid4(), platform_video_id=video_id, program_slug="base", module_slug="m1",
        video_slug="a1", title="Tokens", provider="PANDA_VIDEO", provider_ref="r",
        transcript_status=status,
    )


async def _seed_ready_lesson_with_chunks(video_id: str, chunk_count: int) -> Lesson:
    from src.domain.lessons.entities.lesson_chunk import LessonChunk

    async def _work():
        lesson = await LessonRepository().upsert_from_catalog(_lesson(video_id))
        lesson.transcript_status = TranscriptStatus.READY
        lesson = await LessonRepository().save(lesson)
        chunks = [
            LessonChunk(
                uuid=uuid4(), lesson_id=lesson.uuid, ordinal=i, content=f"trecho {i}",
                start_seconds=i * 10, end_seconds=(i + 1) * 10,
            )
            for i in range(chunk_count)
        ]
        await LessonChunkRepository().replace_for_lesson(lesson.uuid, chunks)
        return lesson

    return await run_in_async_session(_work)


@pytest.mark.asyncio
async def test_sem_sessao_da_401():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/lessons/qualquer/status")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_aula_pronta_devolve_status_e_chunk_count_em_camel_case():
    from main import app

    video_id = f"v-{uuid4()}"
    await _seed_ready_lesson_with_chunks(video_id, 7)
    headers = await auth_headers("aluno@x.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/lessons/{video_id}/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "chunkCount": 7}


@pytest.mark.asyncio
async def test_aula_desconhecida_devolve_200_unknown_nao_404():
    from main import app

    headers = await auth_headers("aluno@x.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/lessons/fantasma/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "unknown", "chunkCount": 0}
