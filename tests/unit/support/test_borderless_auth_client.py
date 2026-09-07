"""Bridge com a plataforma (ADR-0018): signin público, erros por `error.type`,
profile como validação de sessão e signout best-effort."""

import httpx
import pytest

from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
    RateLimitedError,
)

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
        "token": {"accessToken": "opaque-abc", "expiresIn": 604800},
    },
}

PROFILE_BODY = {
    "data": {
        "user": {
            "id": "u-1",
            "name": "Hello",
            "email": "hello@example.com",
            "username": "hello",
            "communityRole": "MEMBER",
            "membership": "BASE",
        }
    }
}


def _error(status: int, type_: str, message: str = "msg") -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": f"AUTH-{type_}-{status}",
                "type": type_,
                "domain": "AUTH",
                "message": message,
                "timestamp": "2026-09-04T12:00:00.000Z",
                "details": {},
            }
        },
    )


def _client(handler) -> BorderlessAuthClient:
    return BorderlessAuthClient(transport=httpx.MockTransport(handler))


# --- sign_in ---


@pytest.mark.asyncio
async def test_signin_e_publico_sem_key_e_parseia_user_e_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = {k.lower() for k in request.headers.keys()}
        return httpx.Response(200, json=OK_BODY)

    result = await _client(handler).sign_in("hello@example.com", "s3nh4")
    assert seen["url"].endswith("/api/auth/signin")
    assert "x-api-key" not in seen["headers"]
    assert "authorization" not in seen["headers"]
    assert result.user.email == "hello@example.com"  # normalizado
    assert result.user.career_stage == "junior_transition"
    assert result.access_token == "opaque-abc"
    assert result.expires_in == 604800


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,type_", [(400, "VALIDATION"), (401, "UNAUTHORIZED"), (400, "UNAUTHORIZED")]
)
async def test_validation_e_unauthorized_viram_invalid_credentials(status, type_):
    with pytest.raises(InvalidCredentialsError):
        await _client(lambda _: _error(status, type_)).sign_in("a@x.com", "errada")


@pytest.mark.asyncio
async def test_forbidden_carrega_a_message_da_plataforma():
    def handler(_):
        return _error(403, "FORBIDDEN", "Sua conta está desativada.")

    with pytest.raises(ForbiddenError) as exc:
        await _client(handler).sign_in("a@x.com", "s")
    assert str(exc.value) == "Sua conta está desativada."


@pytest.mark.asyncio
async def test_too_many_requests_vira_rate_limited():
    with pytest.raises(RateLimitedError):
        await _client(lambda _: _error(429, "TOO_MANY_REQUESTS")).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_internal_5xx_e_rede_viram_unavailable():
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(500, "INTERNAL")).sign_in("a@x.com", "s")

    def handler_net(_):
        raise httpx.ConnectError("down")

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_net).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_status_sem_envelope_cai_no_mapeamento_por_status():
    """Envelope ausente (proxy, HTML) — o status ainda diz o essencial."""
    with pytest.raises(InvalidCredentialsError):
        await _client(lambda _: httpx.Response(401, text="nope")).sign_in("a@x.com", "s")
    with pytest.raises(RateLimitedError):
        await _client(lambda _: httpx.Response(429, text="slow")).sign_in("a@x.com", "s")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(502, text="bad")).sign_in("a@x.com", "s")
    # 403 sem envelope (proxy/WAF): não há message da plataforma para mostrar —
    # tratar como "conta desativada" seria inventar um diagnóstico.
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(403, text="<html>blocked</html>")).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_type_desconhecido_cai_no_mapeamento_por_status():
    """Um `type` fora do contrato documentado não pode virar 503 para um 401
    rotineiro: o status é o fallback também neste caso."""
    with pytest.raises(InvalidCredentialsError):
        await _client(lambda _: _error(401, "INVALID_EMAIL_OR_PASSWORD")).sign_in("a@x.com", "s")
    with pytest.raises(RateLimitedError):
        await _client(lambda _: _error(429, "RATE_LIMITED")).sign_in("a@x.com", "s")
    with pytest.raises(ForbiddenError) as exc:
        await _client(lambda _: _error(403, "ACCOUNT_BANNED", "Banido.")).sign_in("a@x.com", "s")
    assert str(exc.value) == "Banido."


@pytest.mark.asyncio
async def test_200_com_corpo_fora_do_contrato_vira_unavailable():
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(200, json={"data": {}})).sign_in("a@x.com", "s")


# --- get_profile ---


@pytest.mark.asyncio
async def test_get_profile_200_manda_bearer_sem_cookie_e_parseia():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["cookie"] = request.headers.get("cookie")
        return httpx.Response(200, json=PROFILE_BODY)

    profile = await _client(handler).get_profile("opaque-abc")
    assert seen["url"].endswith("/api/users/profile")
    assert seen["auth"] == "Bearer opaque-abc"
    assert seen["cookie"] is None
    assert profile.id == "u-1"
    assert profile.email == "hello@example.com"
    assert profile.membership == "BASE"
    assert profile.community_role == "MEMBER"


@pytest.mark.asyncio
async def test_get_profile_401_ou_403_devolve_none():
    """401 = sessão expirada/revogada; 403 = conta desativada/banida. Nos dois
    a sessão do oráculo morre — 403 NÃO é 'plataforma fora' (fail-open)."""
    assert await _client(lambda _: _error(401, "UNAUTHORIZED")).get_profile("x") is None
    assert await _client(lambda _: _error(403, "FORBIDDEN", "Conta desativada.")).get_profile("x") is None


@pytest.mark.asyncio
async def test_get_profile_rede_5xx_429_e_fora_do_contrato_lancam_unavailable():
    def handler_net(_):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_net).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(500, "INTERNAL")).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(429, "TOO_MANY_REQUESTS")).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(200, json={"data": {}})).get_profile("x")


# --- sign_out ---


@pytest.mark.asyncio
async def test_sign_out_manda_bearer_e_engole_erros():
    seen = {}

    def handler_ok(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"message": "ok"})

    await _client(handler_ok).sign_out("opaque-abc")
    assert seen["url"].endswith("/api/auth/signout")
    assert seen["auth"] == "Bearer opaque-abc"

    def handler_net(_):
        raise httpx.ConnectError("down")

    await _client(handler_net).sign_out("opaque-abc")  # não lança
    await _client(lambda _: _error(500, "INTERNAL")).sign_out("opaque-abc")  # não lança
