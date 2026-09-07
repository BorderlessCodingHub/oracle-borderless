"""ResolveSessionAction (ADR-0018, spec §2): cookie → sessão → validação com
cache de 60s; 401 da plataforma apaga a sessão; fail-open limitado a 10min."""

from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.actions.resolve_session_action import (
    FAIL_OPEN_MAX_S,
    PLATFORM_CHECK_TTL_S,
    ResolveSessionAction,
)
from src.domain.users.entities.user_session import UserSession
from src.support.utils.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import PlatformProfile
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.core.settings import settings

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
RAW = "token-cru-de-teste"


def _session(checked_seconds_ago: int) -> UserSession:
    checked = NOW - timedelta(seconds=checked_seconds_ago)
    return UserSession(
        uuid=uuid7(), token_hash=hash_session_token(RAW), platform_access_token="opaque-abc",
        user_id="u-1", user_email="ana@x.com", user_name="Ana", user_username="ana",
        last_platform_check_at=checked, created_at=checked, updated_at=checked,
    )


class FakeSessions:
    def __init__(self, row: UserSession | None):
        self.row = row
        self.marked: list[tuple] = []
        self.deleted: list = []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def mark_platform_checked(self, session_id, checked_at):
        self.marked.append((session_id, checked_at))

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    """`outcome`: PlatformProfile | None (401) | Exception (rede)."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def get_profile(self, access_token):
        self.calls.append(access_token)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


PROFILE = PlatformProfile(id="u-1", email="ana@x.com", name="Ana", username="ana", membership="BASE", community_role="MEMBER")


def _action(sessions, client):
    return ResolveSessionAction(auth_client=client, sessions=sessions, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_sessao_inexistente_devolve_none_sem_ir_a_plataforma():
    client = FakeClient(PROFILE)
    assert await _action(FakeSessions(None), client).execute("qualquer") is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_dentro_do_cache_nao_chama_a_plataforma(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")
    sessions, client = FakeSessions(_session(PLATFORM_CHECK_TTL_S - 1)), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(RAW)
    assert client.calls == []
    assert sessions.marked == []
    assert (user.id, user.email, user.is_admin, user.name, user.username) == ("u-1", "ana@x.com", True, "Ana", "ana")


@pytest.mark.asyncio
async def test_fora_do_cache_valida_e_atualiza_o_carimbo():
    row = _session(PLATFORM_CHECK_TTL_S)
    sessions, client = FakeSessions(row), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(RAW)
    assert client.calls == ["opaque-abc"]
    assert sessions.marked == [(row.uuid, NOW)]
    assert user.email == "ana@x.com"
    assert user.is_admin is False


@pytest.mark.asyncio
async def test_401_da_plataforma_apaga_a_sessao_e_devolve_none():
    row = _session(PLATFORM_CHECK_TTL_S + 5)
    sessions = FakeSessions(row)
    assert await _action(sessions, FakeClient(None)).execute(RAW) is None
    assert sessions.deleted == [row.uuid]
    assert sessions.marked == []


@pytest.mark.asyncio
async def test_plataforma_fora_dentro_da_janela_estendida_segue_em_fail_open():
    row = _session(FAIL_OPEN_MAX_S - 1)
    sessions = FakeSessions(row)
    user = await _action(sessions, FakeClient(ExternalServiceUnavailableError("down"))).execute(RAW)
    assert user is not None and user.email == "ana@x.com"
    assert sessions.marked == []  # não finge que validou
    assert sessions.deleted == []


@pytest.mark.asyncio
async def test_plataforma_fora_alem_da_janela_estendida_propaga_unavailable():
    sessions = FakeSessions(_session(FAIL_OPEN_MAX_S))
    with pytest.raises(ExternalServiceUnavailableError):
        await _action(sessions, FakeClient(ExternalServiceUnavailableError("down"))).execute(RAW)
    assert sessions.deleted == []  # sessão fica; a plataforma é quem decide
