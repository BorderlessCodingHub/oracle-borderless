"""ResolveBearerAction: header Authorization → sessão por hash do token da
plataforma → find-or-create validando em /api/users/profile. Reusa o cache/
fail-open de ResolveSessionAction quando a sessão já existe."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from src.domain.users.actions.resolve_bearer_action import ResolveBearerAction
from src.domain.users.actions.resolve_session_action import PLATFORM_CHECK_TTL_S
from src.domain.users.entities.user_session import UserSession
from src.support.clients.borderless.borderless_auth_client import PlatformProfile
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.utils.session_tokens import hash_session_token

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
BEARER = "opaque-platform-token"
PROFILE = PlatformProfile(
    id="u-1", email="ana@x.com", name="Ana", username="ana", membership="STARTER",
    community_role="MEMBER", seniority="JUNIOR", career_stage="junior_transition",
)


class FakeSessions:
    """Espelha `UserSessionRepository`: `create_if_absent` embrulha `create`
    e traduz o IntegrityError do unique index de `token_hash` em None — é o
    que o savepoint do repositório real faz."""

    def __init__(self, row: UserSession | None = None, conflict_row: UserSession | None = None):
        self.row = row
        self.conflict_row = conflict_row  # linha que a requisição concorrente grava
        self.created: list[UserSession] = []
        self.snapshots: list[tuple] = []
        self.deleted: list = []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def create(self, session):
        if self.conflict_row is not None:
            # A concorrente venceu a corrida: a linha já está lá quando o INSERT chega.
            self.row, self.conflict_row = self.conflict_row, None
            raise IntegrityError("INSERT INTO sessions", {}, Exception("duplicate key value"))
        self.created.append(session)
        self.row = session
        return session

    async def create_if_absent(self, session):
        try:
            return await self.create(session)
        except IntegrityError:
            return None

    async def mark_platform_checked(self, session_id, checked_at):
        pass

    async def update_profile_snapshot(self, session_id, checked_at, membership, seniority, career_stage):
        self.snapshots.append((session_id, membership, seniority, career_stage))

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[str] = []

    async def get_profile(self, access_token):
        self.calls.append(access_token)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _existing(checked_seconds_ago=0) -> UserSession:
    checked = NOW - timedelta(seconds=checked_seconds_ago)
    return UserSession(
        uuid=uuid7(), token_hash=hash_session_token(BEARER), platform_access_token=BEARER,
        user_id="u-1", user_email="ana@x.com", user_name="Ana", user_username="ana",
        last_platform_check_at=checked, created_at=checked, updated_at=checked,
        source="platform_bearer", user_membership="FREE", user_seniority=None, user_career_stage="curious",
    )


def _action(sessions, client):
    return ResolveBearerAction(auth_client=client, sessions=sessions, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_bearer_desconhecido_valido_cria_sessao_com_snapshot_do_perfil():
    sessions, client = FakeSessions(None), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == [BEARER]
    assert len(sessions.created) == 1
    created = sessions.created[0]
    assert created.token_hash == hash_session_token(BEARER)
    assert created.platform_access_token == BEARER
    assert created.source == "platform_bearer"
    assert (created.user_membership, created.user_seniority, created.user_career_stage) == ("STARTER", "JUNIOR", "junior_transition")
    assert created.last_platform_check_at == NOW
    assert user is not None
    assert (user.id, user.email, user.platform_access_token) == ("u-1", "ana@x.com", BEARER)
    assert (user.membership, user.seniority, user.career_stage) == ("STARTER", "JUNIOR", "junior_transition")


@pytest.mark.asyncio
async def test_bearer_desconhecido_invalido_devolve_none_sem_criar_sessao():
    sessions, client = FakeSessions(None), FakeClient(None)
    assert await _action(sessions, client).execute(BEARER) is None
    assert sessions.created == []


@pytest.mark.asyncio
async def test_bearer_desconhecido_com_plataforma_fora_propaga_503():
    sessions, client = FakeSessions(None), FakeClient(ExternalServiceUnavailableError("fora"))
    with pytest.raises(ExternalServiceUnavailableError):
        await _action(sessions, client).execute(BEARER)
    assert sessions.created == []


@pytest.mark.asyncio
async def test_bearer_conhecido_dentro_do_cache_nao_vai_a_plataforma_e_le_o_snapshot():
    sessions, client = FakeSessions(_existing(PLATFORM_CHECK_TTL_S - 1)), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == []
    assert user is not None
    assert user.platform_access_token == BEARER
    assert (user.membership, user.seniority, user.career_stage) == ("FREE", None, "curious")


@pytest.mark.asyncio
async def test_bearer_conhecido_fora_do_cache_revalida_e_atualiza_o_snapshot():
    row = _existing(PLATFORM_CHECK_TTL_S + 1)
    sessions, client = FakeSessions(row), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == [BEARER]
    assert sessions.snapshots == [(row.uuid, "STARTER", "JUNIOR", "junior_transition")]
    assert (user.membership, user.seniority, user.career_stage) == ("STARTER", "JUNIOR", "junior_transition")


@pytest.mark.asyncio
async def test_bearer_conhecido_revogado_na_plataforma_apaga_a_sessao_e_devolve_none():
    row = _existing(PLATFORM_CHECK_TTL_S + 1)
    sessions, client = FakeSessions(row), FakeClient(None)
    assert await _action(sessions, client).execute(BEARER) is None
    assert sessions.deleted == [row.uuid]


@pytest.mark.asyncio
async def test_bearer_vazio_devolve_none_sem_consultar_nada():
    sessions, client = FakeSessions(None), FakeClient(PROFILE)
    assert await _action(sessions, client).execute("   ") is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_corrida_de_dois_primeiros_requests_com_o_mesmo_bearer_nao_estoura():
    """Header bar e painel de chat abrem juntos logo depois do login na
    Platform: os dois resolvem o MESMO bearer novo ao mesmo tempo. O INSERT
    perdedor bate no unique index de `sessions.token_hash` (migration 0009);
    sem savepoint isso viraria 500. O perdedor relê a linha da vencedora e
    segue pelo caminho da sessão conhecida."""
    winner = _existing(PLATFORM_CHECK_TTL_S - 1)
    sessions = FakeSessions(row=None, conflict_row=winner)
    client = FakeClient(PROFILE)

    user = await _action(sessions, client).execute(BEARER)

    assert sessions.created == []  # o INSERT perdedor não gravou nada
    assert user is not None
    # Delegou a ResolveSessionAction como no caminho da sessão existente: dentro
    # do cache de 60s ele NÃO revalida (a única chamada é a validação do bearer novo).
    assert client.calls == [BEARER]
    assert user.platform_access_token == BEARER
    assert (user.membership, user.seniority, user.career_stage) == ("FREE", None, "curious")
    assert user.session_source == "platform_bearer"
