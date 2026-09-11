import httpx
import pytest

from src.support.clients.borderless.borderless_lessons_client import (
    BorderlessLessonsClient,
    LessonCatalogUnavailableError,
)
from src.support.core.settings import settings


def client_with(handler) -> BorderlessLessonsClient:
    return BorderlessLessonsClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_lists_lessons_and_maps_every_field(monkeypatch):
    monkeypatch.setattr(settings, "BORDERLESS_INTERNAL_SECRET", "test-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-internal-secret"] == "test-secret"
        assert request.url.path == "/api/internal/programs/base/lessons"
        return httpx.Response(200, json={"data": {"lessons": [{
            "id": "v1", "programSlug": "base", "moduleSlug": "m1", "videoSlug": "a1",
            "title": "Tokens", "provider": "PANDA_VIDEO", "providerRef": "ref-1",
            "durationSeconds": None,
        }]}})

    lessons = await client_with(handler).list_program_lessons("base")

    assert len(lessons) == 1
    assert lessons[0].platform_video_id == "v1"
    assert lessons[0].provider_ref == "ref-1"
    assert lessons[0].duration_seconds is None


@pytest.mark.asyncio
async def test_the_secret_never_appears_in_the_url(monkeypatch):
    monkeypatch.setattr(settings, "BORDERLESS_INTERNAL_SECRET", "test-secret")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": {"lessons": []}})

    await client_with(handler).list_program_lessons("base")
    assert all("secret" not in url.lower() for url in seen)
    assert all("test-secret" not in url for url in seen)


@pytest.mark.asyncio
async def test_unknown_program_raises_unavailable_with_the_status():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "program not found"}})

    with pytest.raises(LessonCatalogUnavailableError) as exc:
        await client_with(handler).list_program_lessons("ghost")
    assert "404" in str(exc.value)


@pytest.mark.asyncio
async def test_media_maps_the_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/videos/v1/media"
        return httpx.Response(200, json={"data": {
            "url": "https://cdn.test/a.m3u8", "expiresAt": None, "contentType": "application/vnd.apple.mpegurl",
        }})

    media = await client_with(handler).get_media("v1")
    assert media.url == "https://cdn.test/a.m3u8"
    assert media.content_type == "application/vnd.apple.mpegurl"


@pytest.mark.asyncio
async def test_lesson_row_missing_a_field_raises_unavailable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"lessons": [{
            "id": "v1", "programSlug": "base", "videoSlug": "a1",
            "title": "Tokens", "provider": "PANDA_VIDEO", "providerRef": "ref-1",
            "durationSeconds": None,
        }]}})  # missing moduleSlug

    with pytest.raises(LessonCatalogUnavailableError):
        await client_with(handler).list_program_lessons("base")


@pytest.mark.asyncio
async def test_media_without_url_raises_unavailable():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "expiresAt": None, "contentType": "video/mp4",
        }})

    with pytest.raises(LessonCatalogUnavailableError):
        await client_with(handler).get_media("v1")
