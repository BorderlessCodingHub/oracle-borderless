"""Guards (ADR-0018): cookie → ResolveSessionAction; 401 único em tudo que não
prova identidade; admin por allowlist (404)."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.core.context import CurrentRequestContext
from src.support.core.exceptions import ExternalServiceUnavailableError, NotFoundError
from src.support.core.settings import settings

ANA = AuthenticatedUser(id="u-1", email="ana@x.com", is_admin=False, name="Ana", username="ana")


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _request_with_auth(header: str, cookie: str | None = None) -> Request:
    headers = [(b"authorization", header.encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class FakeResolve:
    """Substitui ResolveSessionAction no módulo: registra o token recebido e
    devolve/lança o que o teste mandar."""

    seen: list[str] = []
    outcome = None

    def __init__(self, auth_client=None, **kw):
        pass

    async def execute(self, raw_token):
        FakeResolve.seen.append(raw_token)
        if isinstance(FakeResolve.outcome, Exception):
            raise FakeResolve.outcome
        return FakeResolve.outcome


class FakeResolveBearer:
    """Substitui ResolveBearerAction no módulo: registra o token recebido e
    devolve/lança o que o teste mandar."""

    seen: list[str] = []
    outcome = None

    def __init__(self, auth_client=None, **kw):
        pass

    async def execute(self, raw_bearer):
        FakeResolveBearer.seen.append(raw_bearer)
        if isinstance(FakeResolveBearer.outcome, Exception):
            raise FakeResolveBearer.outcome
        return FakeResolveBearer.outcome


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    import src.app.api.dependencies.require_user as mod

    FakeResolve.seen, FakeResolve.outcome = [], None
    FakeResolveBearer.seen, FakeResolveBearer.outcome = [], None
    monkeypatch.setattr(mod, "ResolveSessionAction", FakeResolve)
    monkeypatch.setattr(mod, "ResolveBearerAction", FakeResolveBearer)
    yield
    CurrentRequestContext.clear()


@pytest.mark.asyncio
async def test_cookie_valido_devolve_user_e_preenche_o_contexto():
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = ANA
    user = await require_user(_request(f"{SESSION_COOKIE_NAME}=tok-123; outro=x"))
    assert user is ANA
    assert FakeResolve.seen == ["tok-123"]
    assert CurrentRequestContext.get_user() is ANA


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie", [None, "outro=x", f"{SESSION_COOKIE_NAME}=", f"{SESSION_COOKIE_NAME}=   "])
async def test_sem_cookie_de_sessao_da_401_sem_consultar_nada(cookie):
    from src.app.api.dependencies.require_user import require_user

    with pytest.raises(HTTPException) as exc:
        await require_user(_request(cookie))
    assert exc.value.status_code == 401
    assert exc.value.detail == "not-authenticated"
    assert exc.value.headers is None  # nada a apagar: não veio cookie
    assert FakeResolve.seen == []


@pytest.mark.asyncio
async def test_sessao_desconhecida_ou_revogada_da_401_generico():
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = None
    with pytest.raises(HTTPException) as exc:
        await require_user(_request(f"{SESSION_COOKIE_NAME}=nao-existe"))
    assert exc.value.status_code == 401
    assert exc.value.detail == "not-authenticated"
    assert CurrentRequestContext.get_user() is None
    # Cookie morto é apagado junto com o 401 — o browser não fica replicando-o.
    set_cookie = exc.value.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie


@pytest.mark.asyncio
async def test_plataforma_fora_alem_do_fail_open_propaga_unavailable():
    """Não é 401 (o usuário não fez nada errado): a exceção de domínio sobe e o
    exception handler traduz em 503 `unavailable`."""
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = ExternalServiceUnavailableError("down")
    with pytest.raises(ExternalServiceUnavailableError):
        await require_user(_request(f"{SESSION_COOKIE_NAME}=tok"))


@pytest.mark.asyncio
async def test_require_admin_404_para_nao_admin(monkeypatch):
    from src.app.api.dependencies.require_admin import require_admin

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "admin@x.com")
    with pytest.raises(NotFoundError):
        await require_admin(AuthenticatedUser(id="u", email="a@x.com", is_admin=False))
    admin = AuthenticatedUser(id="u", email="admin@x.com", is_admin=True)
    assert await require_admin(admin) is admin


@pytest.mark.asyncio
async def test_bearer_valido_devolve_user_sem_olhar_o_cookie():
    from src.app.api.dependencies.require_user import require_user

    FakeResolveBearer.outcome = ANA
    user = await require_user(_request_with_auth("Bearer plat-123", f"{SESSION_COOKIE_NAME}=cookie-x"))
    assert user is ANA
    assert FakeResolveBearer.seen == ["plat-123"]
    assert FakeResolve.seen == []
    assert CurrentRequestContext.get_user() is ANA


@pytest.mark.asyncio
async def test_bearer_invalido_da_401_sem_apagar_cookie():
    from src.app.api.dependencies.require_user import require_user

    FakeResolveBearer.outcome = None
    with pytest.raises(HTTPException) as exc:
        await require_user(_request_with_auth("Bearer nope"))
    assert exc.value.status_code == 401
    assert exc.value.headers is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer   ", "bearer x y"])
async def test_authorization_malformado_cai_no_caminho_do_cookie(header):
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = ANA
    user = await require_user(_request_with_auth(header, f"{SESSION_COOKIE_NAME}=tok-1"))
    assert user is ANA
    assert FakeResolveBearer.seen == []
