"""Sessões de teste (ADR-0018).

`seed_session` grava uma linha em `sessions` já validada (`last_platform_check_at`
= agora → dentro do cache de 60s, o `require_user` NÃO vai à plataforma) e
devolve o token CRU; `cookie_headers` monta o header `Cookie` que o SPA
mandaria. Tudo que foi semeado é apagado no fim da sessão de testes
(`purge_seeded_sessions`, chamado pelo conftest).
"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.domain.users.services.session_tokens import generate_session_token, hash_session_token
from src.support.core.session_scope import run_in_async_session
from src.support.core.settings import settings

_SEEDED_HASHES: list[str] = []


async def seed_session(
    email: str,
    *,
    user_id: str = "user-1",
    name: str | None = None,
    username: str | None = None,
    platform_token: str = "plat-token-teste",
    checked_at: datetime | None = None,
) -> str:
    raw = generate_session_token()
    token_hash = hash_session_token(raw)
    now = datetime.now(timezone.utc)

    async def _work():
        await UserSessionRepository().create(
            UserSession(
                uuid=uuid7(),
                token_hash=token_hash,
                platform_access_token=platform_token,
                user_id=user_id,
                user_email=email.strip().lower(),
                user_name=name,
                user_username=username,
                last_platform_check_at=checked_at or now,
                created_at=now,
                updated_at=now,
            )
        )

    await run_in_async_session(_work)
    _SEEDED_HASHES.append(token_hash)
    return raw


def cookie_headers(raw_token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}


async def auth_headers(email: str, **kw) -> dict[str, str]:
    """Substituto direto do `auth_headers` da v1 — agora assíncrono."""
    return cookie_headers(await seed_session(email, **kw))


async def purge_seeded_sessions() -> None:
    """Engine própria (o `engine` global pode estar preso a um loop já fechado)."""
    if not _SEEDED_HASHES:
        return
    engine = create_async_engine(settings.database_url_async, poolclass=None)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession)
    try:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM sessions WHERE token_hash = ANY(:hashes)"),
                {"hashes": list(_SEEDED_HASHES)},
            )
            await session.commit()
    finally:
        await engine.dispose()
        _SEEDED_HASHES.clear()
