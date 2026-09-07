"""POST /auth/login, GET /auth/me, POST /auth/logout — BFF (ADR-0018).
Plataforma mockada nos dois pontos de uso (controller e require_user)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.support.utils.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import (
    PlatformProfile,
    PlatformSignIn,
    PlatformUser,
)
from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
)
from src.support.core.settings import settings
from tests.fakes.auth import auth_headers, cookie_headers, seed_session


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    yield
    from src.support.core.database import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def api_client():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class FakePlatform:
    """Uma classe só, instanciada pelo controller E pelo require_user; o estado
    fica em atributos de classe para o teste inspecionar."""

    signed_out: list[str] = []
    profile_calls: list[str] = []
    sign_in_error: Exception | None = None
    profile_outcome = "ok"  # "ok" | None (401) | "down"

    @classmethod
    def reset(cls):
        cls.signed_out, cls.profile_calls, cls.sign_in_error, cls.profile_outcome = [], [], None, "ok"

    def __init__(self, transport=None):
        pass

    async def sign_in(self, email, password):
        if FakePlatform.sign_in_error:
            raise FakePlatform.sign_in_error
        return PlatformSignIn(
            user=PlatformUser(id="u-1", email=email, name="Ana", username="ana",
                              career_stage="junior_transition", email_verified=True),
            access_token="plat-abc",
            expires_in=604800,
        )

    async def get_profile(self, access_token):
        FakePlatform.profile_calls.append(access_token)
        if FakePlatform.profile_outcome == "down":
            raise ExternalServiceUnavailableError("down")
        if FakePlatform.profile_outcome is None:
            return None
        return PlatformProfile(id="u-1", email="ana@x.com", name="Ana", username="ana",
                               membership="BASE", community_role="MEMBER")

    async def sign_out(self, access_token):
        FakePlatform.signed_out.append(access_token)


@pytest.fixture(autouse=True)
def _fake_platform(monkeypatch):
    import src.app.api.controllers.auth_controller as ctrl
    import src.app.api.dependencies.require_user as dep

    FakePlatform.reset()
    monkeypatch.setattr(ctrl, "BorderlessAuthClient", FakePlatform)
    monkeypatch.setattr(dep, "BorderlessAuthClient", FakePlatform)


def _unique_email() -> str:
    # E-mail único por execução: o rate limit do login é REAL (tabela
    # rate_limits) e acumularia entre rodadas da suíte.
    return f"ana-{uuid4().hex[:8]}@x.com"


async def _session_row(raw_token: str) -> dict | None:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text("SELECT platform_access_token, user_email FROM sessions WHERE token_hash = :h"),
                {"h": hash_session_token(raw_token)},
            )
        ).mappings().first()
        return dict(row) if row else None


async def _delete_session_row(raw_token: str) -> None:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM sessions WHERE token_hash = :h"), {"h": hash_session_token(raw_token)})
        await s.commit()


@pytest.mark.asyncio
async def test_login_seta_cookie_httponly_cria_sessao_e_nao_expoe_token(api_client, monkeypatch):
    email = _unique_email()
    monkeypatch.setattr(settings, "ADMIN_EMAILS", email)

    resp = await api_client.post("/auth/login", json={"email": email.upper(), "password": "s3nh4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "user": {"id": "u-1", "email": email, "name": "Ana", "username": "ana"},
        "is_admin": True,
    }
    assert "plat-abc" not in resp.text

    set_cookie = resp.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=604800" in set_cookie
    assert "secure" not in set_cookie  # ENVIRONMENT=development

    raw = api_client.cookies.get(SESSION_COOKIE_NAME)
    assert raw
    row = await _session_row(raw)
    assert row == {"platform_access_token": "plat-abc", "user_email": email}

    await _delete_session_row(raw)


@pytest.mark.asyncio
async def test_login_me_logout_fim_a_fim(api_client):
    email = _unique_email()
    login = await api_client.post("/auth/login", json={"email": email, "password": "s3nh4"})
    assert login.status_code == 200
    raw = api_client.cookies.get(SESSION_COOKIE_NAME)

    # /auth/me com o cookie que o client guardou (dentro do cache → sem ida à plataforma)
    me = await api_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email
    assert FakePlatform.profile_calls == []
    # Janela deslizante: o restore reemite o cookie com Max-Age cheio.
    renovado = me.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}={raw.lower()}" in renovado
    assert "max-age=604800" in renovado

    logout = await api_client.post("/auth/logout")
    assert logout.status_code == 204
    assert FakePlatform.signed_out == ["plat-abc"]
    set_cookie = logout.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie
    assert await _session_row(raw) is None

    # O cookie antigo não vale mais nada.
    depois = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert depois.status_code == 401


@pytest.mark.asyncio
async def test_me_sem_cookie_da_401(api_client):
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "not-authenticated"


@pytest.mark.asyncio
async def test_logout_sem_cookie_e_204_idempotente(api_client):
    """Logout é público e idempotente: nada a encerrar, mas o cookie é apagado."""
    resp = await api_client.post("/auth/logout")
    assert resp.status_code == 204
    assert "max-age=0" in resp.headers["set-cookie"].lower()
    assert FakePlatform.signed_out == []


@pytest.mark.asyncio
async def test_logout_funciona_mesmo_com_a_plataforma_fora_alem_do_fail_open(api_client):
    """O caso que motivou o logout público: `require_user` daria 503 aqui, e o
    cookie sobreviveria — com a plataforma de volta o usuário reapareceria
    logado. O logout tem que apagar a sessão local de qualquer jeito."""
    FakePlatform.profile_outcome = "down"
    muito_velha = datetime.now(timezone.utc) - timedelta(minutes=11)
    raw = await seed_session("ana@x.com", platform_token="plat-x", checked_at=muito_velha)

    resp = await api_client.post("/auth/logout", headers=cookie_headers(raw))
    assert resp.status_code == 204
    assert await _session_row(raw) is None
    assert FakePlatform.signed_out == ["plat-x"]  # best-effort: o fake aceitou


@pytest.mark.asyncio
async def test_login_invalido_devolve_401_com_codigo_estavel(api_client):
    FakePlatform.sign_in_error = InvalidCredentialsError("nope")
    resp = await api_client.post("/auth/login", json={"email": _unique_email(), "password": "errada"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid-credentials"}
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_login_forbidden_repassa_a_message_da_plataforma(api_client):
    FakePlatform.sign_in_error = ForbiddenError("Sua conta está desativada.")
    resp = await api_client.post("/auth/login", json={"email": _unique_email(), "password": "s"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "forbidden", "message": "Sua conta está desativada."}


@pytest.mark.asyncio
async def test_sessao_fora_do_cache_e_revogada_na_plataforma_da_401_e_apaga(api_client):
    FakePlatform.profile_outcome = None  # plataforma diz 401
    stale = datetime.now(timezone.utc) - timedelta(minutes=2)
    raw = await seed_session("ana@x.com", platform_token="plat-velho", checked_at=stale)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 401
    assert FakePlatform.profile_calls == ["plat-velho"]
    assert await _session_row(raw) is None
    # e o browser recebe a ordem de apagar o cookie morto
    assert "max-age=0" in resp.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_sessao_fora_do_cache_valida_na_plataforma_e_renova_o_carimbo(api_client):
    stale = datetime.now(timezone.utc) - timedelta(minutes=2)
    raw = await seed_session("ana@x.com", platform_token="plat-ok", checked_at=stale)

    primeira = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert primeira.status_code == 200
    segunda = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert segunda.status_code == 200
    assert FakePlatform.profile_calls == ["plat-ok"]  # a segunda veio do cache


@pytest.mark.asyncio
async def test_plataforma_fora_alem_do_fail_open_da_503(api_client):
    FakePlatform.profile_outcome = "down"
    muito_velha = datetime.now(timezone.utc) - timedelta(minutes=11)
    raw = await seed_session("ana@x.com", checked_at=muito_velha)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 503
    assert resp.json() == {"detail": "unavailable"}


@pytest.mark.asyncio
async def test_plataforma_fora_dentro_do_fail_open_segue(api_client):
    FakePlatform.profile_outcome = "down"
    recente = datetime.now(timezone.utc) - timedelta(minutes=5)
    raw = await seed_session("ana@x.com", checked_at=recente)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_conversations_com_cookie_semeado_passa(api_client):
    resp = await api_client.get("/conversations", headers=await auth_headers("ana@x.com"))
    assert resp.status_code == 200
