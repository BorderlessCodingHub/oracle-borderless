"""Cookie → sessão → identidade (ADR-0018, spec §2).

Valida a sessão contra a plataforma (`GET /api/users/profile`) com cache de
60s por sessão: banimento/revogação refletem em ≤60s. Se a plataforma está
fora (rede/5xx), segue em fail-open enquanto a última validação boa tiver
menos de 10min — depois disso propaga `ExternalServiceUnavailableError` (503),
para uma sessão não se validar sozinha para sempre.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.support.utils.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

PLATFORM_CHECK_TTL_S = 60
FAIL_OPEN_MAX_S = 600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResolveSessionAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()
        self.clock = clock or _utcnow

    async def execute(self, raw_token: str) -> AuthenticatedUser | None:
        """None = sem sessão válida (401 genérico no HTTP)."""
        session = await self.sessions.get_by_token_hash(hash_session_token(raw_token))
        if session is None:
            return None

        now = self.clock()
        age = session.seconds_since_platform_check(now)
        if age >= PLATFORM_CHECK_TTL_S:
            try:
                profile = await self.auth_client.get_profile(session.platform_access_token)
            except ExternalServiceUnavailableError:
                if age >= FAIL_OPEN_MAX_S:
                    raise
                logger.warning(
                    "plataforma indisponível; sessão segue em fail-open (%.0fs desde a última validação)",
                    age,
                )
            else:
                if profile is None:
                    # Expirada/revogada na plataforma: a nossa morre junto.
                    await self.sessions.delete(session.uuid)
                    return None
                await self.sessions.mark_platform_checked(session.uuid, now)

        return AuthenticatedUser(
            id=session.user_id,
            email=session.user_email,
            is_admin=session.user_email in settings.admin_emails,
            name=session.user_name,
            username=session.user_username,
        )
