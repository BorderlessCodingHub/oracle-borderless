"""POST /auth/login — bridge com a plataforma (client mockado no controller)."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.support.clients.borderless.borderless_auth_client import (
    PlatformSignIn,
    PlatformUser,
)
from src.support.core.exceptions import InvalidCredentialsError
from src.support.core.settings import settings


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


def _platform_ok(email="ana@x.com"):
    return PlatformSignIn(
        user=PlatformUser(
            id="u-1", email=email, name="Ana", username="ana",
            career_stage="junior_transition", email_verified=True,
        ),
        access_token="jwt-abc",
        expires_in=3600,
    )


@pytest.mark.asyncio
async def test_login_ok_devolve_user_token_e_is_admin(api_client, monkeypatch):
    import src.app.api.controllers.auth_controller as ctrl

    class FakeClient:
        async def sign_in(self, email, password):
            return _platform_ok(email)

    monkeypatch.setattr(ctrl, "BorderlessAuthClient", FakeClient)
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")

    resp = await api_client.post(
        "/auth/login", json={"email": "Ana@X.com", "password": "s3nh4"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == "ana@x.com"
    assert body["access_token"] == "jwt-abc"
    assert body["expires_in"] == 3600
    assert body["is_admin"] is True


@pytest.mark.asyncio
async def test_login_invalido_devolve_401_com_codigo_estavel(api_client, monkeypatch):
    import src.app.api.controllers.auth_controller as ctrl

    class FakeClient:
        async def sign_in(self, email, password):
            raise InvalidCredentialsError("nope")

    monkeypatch.setattr(ctrl, "BorderlessAuthClient", FakeClient)
    resp = await api_client.post(
        "/auth/login", json={"email": "a@x.com", "password": "errada"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid-credentials"
