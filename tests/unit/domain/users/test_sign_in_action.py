"""SignInAction: normalização, rate limit e isAdmin da allowlist."""

import pytest

from src.support.clients.borderless.borderless_auth_client import (
    PlatformSignIn,
    PlatformUser,
)
from src.support.core.exceptions import InvalidCredentialsError, RateLimitedError
from src.support.core.settings import settings


class FakeAuthClient:
    def __init__(self):
        self.calls = []

    async def sign_in(self, email, password):
        self.calls.append((email, password))
        return PlatformSignIn(
            user=PlatformUser(
                id="u-1", email=email, name="Ana", username="ana",
                career_stage="junior_transition", email_verified=True,
            ),
            access_token="jwt-abc",
            expires_in=3600,
        )


@pytest.fixture(autouse=True)
def _rate_limit_liberado(monkeypatch):
    from src.domain.users.actions import sign_in_action

    async def _ok(key, limit, window_ms):
        return True

    monkeypatch.setattr(sign_in_action, "rate_limit", _ok)


@pytest.mark.asyncio
async def test_normaliza_email_e_devolve_resultado():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake = FakeAuthClient()
    result = await SignInAction(auth_client=fake).execute("  Ana@X.com ", "s3nh4")
    assert fake.calls == [("ana@x.com", "s3nh4")]
    assert result.user.email == "ana@x.com"
    assert result.access_token == "jwt-abc"
    assert result.expires_in == 3600


@pytest.mark.asyncio
async def test_vazios_sao_invalid_credentials_sem_ir_a_rede():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake = FakeAuthClient()
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake).execute("  ", "x")
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake).execute("a@x.com", "")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_rate_limit_estourado_barra_antes_da_rede(monkeypatch):
    from src.domain.users.actions import sign_in_action
    from src.domain.users.actions.sign_in_action import SignInAction

    async def _nao(key, limit, window_ms):
        assert key == "signin:ana@x.com"
        assert (limit, window_ms) == (10, 600_000)
        return False

    monkeypatch.setattr(sign_in_action, "rate_limit", _nao)
    fake = FakeAuthClient()
    with pytest.raises(RateLimitedError):
        await SignInAction(auth_client=fake).execute("ana@x.com", "s")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_is_admin_vem_da_allowlist(monkeypatch):
    from src.domain.users.actions.sign_in_action import SignInAction

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")
    result = await SignInAction(auth_client=FakeAuthClient()).execute("ana@x.com", "s")
    assert result.is_admin is True

    result = await SignInAction(auth_client=FakeAuthClient()).execute("beto@x.com", "s")
    assert result.is_admin is False
