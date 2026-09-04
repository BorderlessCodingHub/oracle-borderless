"""UserSessionRepository: hash único, snapshot, cache de validação e delete."""

from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository


def _session(token_hash: str, email: str = "ana@x.com") -> UserSession:
    now = datetime.now(timezone.utc)
    return UserSession(
        uuid=uuid7(),
        token_hash=token_hash,
        platform_access_token="plat-abc",
        user_id="u-1",
        user_email=email,
        user_name="Ana",
        user_username="ana",
        last_platform_check_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_e_get_by_token_hash(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("h" * 64))
    found = await repo.get_by_token_hash("h" * 64)
    assert found is not None
    assert found.uuid == created.uuid
    assert found.platform_access_token == "plat-abc"
    assert found.user_email == "ana@x.com"
    assert found.user_name == "Ana"
    assert await repo.get_by_token_hash("x" * 64) is None


@pytest.mark.asyncio
async def test_mark_platform_checked_atualiza_o_cache(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("c" * 64))
    later = created.last_platform_check_at + timedelta(minutes=5)
    await repo.mark_platform_checked(created.uuid, later)
    found = await repo.get_by_token_hash("c" * 64)
    assert found.last_platform_check_at == later


@pytest.mark.asyncio
async def test_delete_remove_a_sessao(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("d" * 64))
    await repo.delete(created.uuid)
    assert await repo.get_by_token_hash("d" * 64) is None


@pytest.mark.asyncio
async def test_delete_idle_since_apaga_so_as_anteriores_ao_corte(db_session):
    repo = UserSessionRepository()
    now = datetime.now(timezone.utc)
    velha = _session("v" * 64)
    velha.last_platform_check_at = now - timedelta(days=8)
    recente = _session("r" * 64)
    recente.last_platform_check_at = now - timedelta(days=6)
    await repo.create(velha)
    await repo.create(recente)

    removed = await repo.delete_idle_since(now - timedelta(days=7))
    assert removed == 1
    assert await repo.get_by_token_hash("v" * 64) is None
    assert await repo.get_by_token_hash("r" * 64) is not None
    # idempotente
    assert await repo.delete_idle_since(now - timedelta(days=7)) == 0
