"""Bridge com a plataforma: mapeamento de status e parsing do contrato (§3 do spec)."""

import httpx
import pytest

from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    InvalidCredentialsError,
    RateLimitedError,
)
from src.support.core.settings import settings

OK_BODY = {
    "message": "ok",
    "data": {
        "user": {
            "id": "u-1",
            "email": "Hello@Example.com",
            "name": "Hello",
            "emailVerified": True,
            "username": "hello",
            "careerStage": "junior_transition",
        },
        "token": {"accessToken": "jwt-abc", "expiresIn": 3600},
    },
}


def _client(handler) -> BorderlessAuthClient:
    return BorderlessAuthClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "BORDERLESS_AUTH_API_KEY", "app-key-teste")


@pytest.mark.asyncio
async def test_signin_ok_parseia_user_e_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get(settings.BORDERLESS_AUTH_KEY_HEADER)
        return httpx.Response(200, json=OK_BODY)

    result = await _client(handler).sign_in("hello@example.com", "s3nh4")
    assert seen["url"].endswith("/api/auth/signin")
    assert seen["key"] == "app-key-teste"
    assert result.user.email == "hello@example.com"  # normalizado
    assert result.user.career_stage == "junior_transition"
    assert result.access_token == "jwt-abc"
    assert result.expires_in == 3600


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_4xx_vira_invalid_credentials(status):
    def handler(_): return httpx.Response(status, json={"error": {"code": "x"}})
    with pytest.raises(InvalidCredentialsError):
        await _client(handler).sign_in("a@x.com", "errada")


@pytest.mark.asyncio
async def test_429_vira_rate_limited():
    def handler(_): return httpx.Response(429, json={"error": {"code": "x"}})
    with pytest.raises(RateLimitedError):
        await _client(handler).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_5xx_e_erro_de_rede_viram_unavailable():
    def handler_500(_): return httpx.Response(500)
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_500).sign_in("a@x.com", "s")

    def handler_net(_): raise httpx.ConnectError("down")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_net).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_200_com_corpo_fora_do_contrato_vira_unavailable():
    def handler(_): return httpx.Response(200, json={"data": {}})
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_sem_api_key_configurada_vira_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "BORDERLESS_AUTH_API_KEY", None)
    def handler(_): return httpx.Response(200, json=OK_BODY)
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler).sign_in("a@x.com", "s")
