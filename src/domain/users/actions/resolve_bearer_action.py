"""Bearer da plataforma → sessão do oráculo (find-or-create) → identidade.

Caminho do proxy do Next.js (spec §3/§5.1): o cliente já está logado na
Platform e manda `Authorization: Bearer <token opaco>`. A sessão é chaveada
pelo hash desse token, com `source = "platform_bearer"`, e a partir daí segue
o cache/fail-open de ResolveSessionAction. Um bearer nunca visto é validado
UMA vez em /api/users/profile antes de virar sessão."""

from datetime import datetime, timezone
from typing import Callable

from uuid6 import uuid7

from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.settings import settings
from src.support.utils.session_tokens import hash_session_token

SOURCE_PLATFORM_BEARER = "platform_bearer"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResolveBearerAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()
        self.clock = clock or _utcnow

    async def execute(self, raw_bearer: str) -> AuthenticatedUser | None:
        raw_bearer = (raw_bearer or "").strip()
        if not raw_bearer:
            return None

        existing = await self.sessions.get_by_token_hash(hash_session_token(raw_bearer))
        if existing is not None:
            return await ResolveSessionAction(
                auth_client=self.auth_client, sessions=self.sessions, clock=self.clock
            ).execute(raw_bearer)

        profile = await self.auth_client.get_profile(raw_bearer)
        if profile is None:
            return None

        now = self.clock()
        await self.sessions.create(
            UserSession(
                uuid=uuid7(),
                token_hash=hash_session_token(raw_bearer),
                platform_access_token=raw_bearer,
                user_id=profile.id,
                user_email=profile.email,
                user_name=profile.name,
                user_username=profile.username,
                last_platform_check_at=now,
                created_at=now,
                updated_at=now,
                source=SOURCE_PLATFORM_BEARER,
                user_membership=profile.membership,
                user_seniority=profile.seniority,
                user_career_stage=profile.career_stage,
            )
        )
        return AuthenticatedUser(
            id=profile.id,
            email=profile.email,
            is_admin=profile.email in settings.admin_emails,
            name=profile.name,
            username=profile.username,
            platform_access_token=raw_bearer,
            membership=profile.membership,
            seniority=profile.seniority,
            career_stage=profile.career_stage,
        )
