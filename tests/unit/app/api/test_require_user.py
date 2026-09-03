"""Guards: JWT local (401 em tudo que não prova identidade) e admin (404)."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.support.core.context import CurrentRequestContext
from src.support.core.exceptions import NotFoundError
from src.support.core.settings import settings
from tests.fakes.auth import auth_headers, forge_token


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


@pytest.fixture(autouse=True)
def _clear_context():
    yield
    CurrentRequestContext.clear()


@pytest.mark.asyncio
async def test_token_valido_devolve_user_e_preenche_o_contexto():
    from src.app.api.dependencies.require_user import require_user

    user = await require_user(_request(auth_headers("Ana@X.com")))
    assert user.email == "ana@x.com"  # normalizado
    assert CurrentRequestContext.get_user() is user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        None,
        {"Authorization": "Bearer "},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer nao-e-jwt"},
    ],
)
async def test_sem_bearer_valido_da_401(headers):
    from src.app.api.dependencies.require_user import require_user

    with pytest.raises(HTTPException) as exc:
        await require_user(_request(headers))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_token_expirado_e_assinatura_errada_dao_401():
    from src.app.api.dependencies.require_user import require_user

    expirado = {"Authorization": f"Bearer {forge_token('a@x.com', expires_in=-10)}"}
    with pytest.raises(HTTPException):
        await require_user(_request(expirado))

    forjado = {"Authorization": f"Bearer {forge_token('a@x.com', secret='outro')}"}
    with pytest.raises(HTTPException):
        await require_user(_request(forjado))


@pytest.mark.asyncio
async def test_token_sem_email_da_401():
    import jwt as pyjwt

    from src.app.api.dependencies.require_user import require_user
    from tests.fakes.auth import TEST_JWT_ALGORITHM, TEST_JWT_SECRET

    token = pyjwt.encode(
        {"sub": "u-1", "exp": 4_000_000_000}, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM
    )
    with pytest.raises(HTTPException):
        await require_user(_request({"Authorization": f"Bearer {token}"}))


@pytest.mark.asyncio
async def test_verify_key_ausente_da_503(monkeypatch):
    from src.app.api.dependencies.require_user import require_user

    monkeypatch.setattr(settings, "BORDERLESS_JWT_VERIFY_KEY", None)
    with pytest.raises(HTTPException) as exc:
        await require_user(_request(auth_headers("a@x.com")))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_require_admin_404_para_nao_admin(monkeypatch):
    from src.app.api.dependencies.require_admin import require_admin
    from src.domain.users.entities.authenticated_user import AuthenticatedUser

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "admin@x.com")
    with pytest.raises(NotFoundError):
        await require_admin(AuthenticatedUser(id="u", email="a@x.com", is_admin=False))
    admin = AuthenticatedUser(id="u", email="admin@x.com", is_admin=True)
    assert await require_admin(admin) is admin
