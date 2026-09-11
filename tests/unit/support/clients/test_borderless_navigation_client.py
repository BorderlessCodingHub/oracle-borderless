import json
import httpx
import pytest

from src.support.clients.borderless.borderless_navigation_client import (
    BorderlessNavigationClient, NavigationUnauthorizedError, NavigationValidationError,
)
from src.support.core.exceptions import ExternalServiceUnavailableError

RESOLVED = {"data": {
    "destination": {"id": "trail", "path": "/trails/t1", "label": "Backend Node.js"},
    "access": "locked_upgrade",
    "unlock": {"action": "upgrade", "membership": "STARTER", "path": "/settings/purchases"},
    "signals": {"matchedTags": ["nodejs"], "inProgress": False, "difficulty": "BEGINNER", "fallback": False,
                "profile": {"membership": "FREE", "seniority": "JUNIOR", "careerStage": "junior_transition"}},
    "alternatives": [{"id": "trails", "path": "/trails", "labelKey": "navigation.destinations.trails"}],
}}


def _client(handler):
    return BorderlessNavigationClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_resolve_envia_bearer_e_body_e_parseia_o_resultado():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESOLVED)

    result = await _client(handler).resolve("tok", "trail", topic="backend node", goal="learn")
    assert seen == {"auth": "Bearer tok", "path": "/api/navigation/resolve",
                    "body": {"destination": "trail", "topic": "backend node", "goal": "learn"}}
    assert result.destination["path"] == "/trails/t1"
    assert result.access == "locked_upgrade"
    public = result.to_public()
    assert set(public) == {"destination", "access", "unlock", "signals", "alternatives"}
    assert "profile" not in public["signals"]
    assert "profile" in json.loads(result.to_tool_text())["signals"]


@pytest.mark.asyncio
async def test_resolve_omite_topic_e_goal_quando_none():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESOLVED)

    await _client(handler).resolve("tok", "home")
    assert seen["body"] == {"destination": "home"}


@pytest.mark.asyncio
async def test_400_validation_vira_erro_com_ids_validos():
    def handler(request):
        return httpx.Response(400, json={"error": {"type": "VALIDATION", "message": "Unknown navigation destination",
                                                   "details": {"validDestinations": ["home", "trails"]}}})
    with pytest.raises(NavigationValidationError) as exc:
        await _client(handler).resolve("tok", "moon")
    assert exc.value.valid_destinations == ["home", "trails"]


@pytest.mark.asyncio
async def test_401_vira_unauthorized():
    with pytest.raises(NavigationUnauthorizedError):
        await _client(lambda r: httpx.Response(401, json={"error": {"type": "UNAUTHORIZED"}})).resolve("tok", "home")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "500", "malformed"])
async def test_rede_5xx_ou_contrato_quebrado_viram_service_unavailable(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        if failure == "500":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"data": {"nope": 1}})

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler).resolve("tok", "home")


@pytest.mark.asyncio
async def test_catalog_parseia_destinations():
    body = {"data": {"destinations": [{"id": "home", "kind": "static", "path": "/", "labelKey": "navigation.destinations.home", "description": "Dashboard"}]}}
    entries = await _client(lambda r: httpx.Response(200, json=body)).catalog("tok")
    assert entries[0]["id"] == "home"
