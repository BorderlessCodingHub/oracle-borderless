"""Cliente do entitlement de aula: pergunta à plataforma, COM O BEARER DO
ALUNO, se ele enxerga o vídeo. Rota real (verificada em
borderless-api/src/routes/api/programs.routes.ts):
GET /api/programs/{programSlug}/modules/{moduleSlug}/videos/{videoSlug},
payload `{"data": {"video": {..., "access": {"hasAccess": bool, ...}}}}`
(borderless-platform/src/services/api/programs/types.ts, VideoPageDataSchema).
"""

import httpx
import pytest

from src.support.clients.borderless.borderless_lesson_access_client import (
    BorderlessLessonAccessClient,
)


def client_with(handler) -> BorderlessLessonAccessClient:
    return BorderlessLessonAccessClient(transport=httpx.MockTransport(handler))


def _video_payload(has_access: bool) -> dict:
    return {
        "data": {
            "video": {"id": "v1", "access": {"hasAccess": has_access, "canSeeMetadata": True}},
            "playlist": [],
            "program": {"slug": "base"},
            "module": {"slug": "m1"},
        }
    }


@pytest.mark.asyncio
async def test_has_access_true_when_the_platform_grants_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/programs/base/modules/m1/videos/a1"
        assert request.headers["authorization"] == "Bearer tok"
        assert "x-internal-secret" not in request.headers
        return httpx.Response(200, json=_video_payload(True))

    allowed = await client_with(handler).has_access("tok", "base", "m1", "a1")
    assert allowed is True


@pytest.mark.asyncio
async def test_has_access_false_when_the_platform_denies_it():
    allowed = await client_with(
        lambda r: httpx.Response(200, json=_video_payload(False))
    ).has_access("tok", "base", "m1", "a1")
    assert allowed is False


@pytest.mark.asyncio
async def test_404_means_no_access():
    allowed = await client_with(
        lambda r: httpx.Response(404, json={"error": {"message": "not found"}})
    ).has_access("tok", "base", "m1", "ghost")
    assert allowed is False


@pytest.mark.asyncio
async def test_500_raises():
    with pytest.raises(httpx.HTTPStatusError):
        await client_with(lambda r: httpx.Response(500, text="boom")).has_access(
            "tok", "base", "m1", "a1"
        )
