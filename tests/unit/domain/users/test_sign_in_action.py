"""SignInAction v2 (ADR-0018): normalização, rate limit, cria sessão com hash,
token cru só no resultado, isAdmin da allowlist."""

import pytest

from src.support.utils.session_tokens import hash_session_token
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
            access_token="opaque-abc",
            expires_in=604800,
        )


class FakeSessions:
    def __init__(self):
        self.created = []

    async def create(self, user_session):
        self.created.append(user_session)
        return user_session


@pytest.fixture(autouse=True)
def _rate_limit_liberado(monkeypatch):
    from src.domain.users.actions import sign_in_action

    async def _ok(key, limit, window_ms):
        return True

    monkeypatch.setattr(sign_in_action, "rate_limit", _ok)


@pytest.mark.asyncio
async def test_normaliza_email_cria_sessao_e_devolve_token_cru():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake, sessions = FakeAuthClient(), FakeSessions()
    result = await SignInAction(auth_client=fake, sessions=sessions).execute("  Ana@X.com ", "s3nh4")

    assert fake.calls == [("ana@x.com", "s3nh4")]
    assert result.user.email == "ana@x.com"
    assert result.user.name == "Ana"
    assert len(result.session_token) >= 40

    assert len(sessions.created) == 1
    row = sessions.created[0]
    assert row.token_hash == hash_session_token(result.session_token)
    assert row.token_hash != result.session_token  # o cru não persiste
    assert row.platform_access_token == "opaque-abc"
    assert (row.user_id, row.user_email, row.user_name, row.user_username) == ("u-1", "ana@x.com", "Ana", "ana")
    assert row.last_platform_check_at is not None  # login = validação fresca


@pytest.mark.asyncio
async def test_vazios_sao_invalid_credentials_sem_ir_a_rede():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake, sessions = FakeAuthClient(), FakeSessions()
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("  ", "x")
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("a@x.com", "")
    assert fake.calls == []
    assert sessions.created == []


@pytest.mark.asyncio
async def test_rate_limit_estourado_barra_antes_da_rede(monkeypatch):
    from src.domain.users.actions import sign_in_action
    from src.domain.users.actions.sign_in_action import SignInAction

    async def _nao(key, limit, window_ms):
        assert key == "signin:ana@x.com"
        assert (limit, window_ms) == (10, 600_000)
        return False

    monkeypatch.setattr(sign_in_action, "rate_limit", _nao)
    fake, sessions = FakeAuthClient(), FakeSessions()
    with pytest.raises(RateLimitedError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("ana@x.com", "s")
    assert fake.calls == []
    assert sessions.created == []


@pytest.mark.asyncio
async def test_is_admin_vem_da_allowlist(monkeypatch):
    from src.domain.users.actions.sign_in_action import SignInAction

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")
    result = await SignInAction(auth_client=FakeAuthClient(), sessions=FakeSessions()).execute("ana@x.com", "s")
    assert result.is_admin is True

    result = await SignInAction(auth_client=FakeAuthClient(), sessions=FakeSessions()).execute("beto@x.com", "s")
    assert result.is_admin is False
