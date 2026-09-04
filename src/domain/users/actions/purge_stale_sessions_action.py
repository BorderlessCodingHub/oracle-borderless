"""Faxina de `sessions` (ADR-0018).

A plataforma expira a sessão dela após 7 dias sem uso e o cookie do oráculo tem
Max-Age de 7 dias — uma linha sem validação há mais de 7 dias está morta dos
dois lados e nunca mais será alcançada por um request (logo, nunca seria
apagada pelo `ResolveSessionAction`). Sem esta faxina a tabela cresce sem limite
guardando accessTokens em claro. Idempotente por construção.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from src.domain.users.repositories.user_session_repository import UserSessionRepository

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(days=7)


class PurgeStaleSessionsAction:
    def __init__(
        self,
        sessions: UserSessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = sessions if sessions is not None else UserSessionRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def execute(self) -> int:
        cutoff = self.clock() - STALE_AFTER
        removed = await self.sessions.delete_idle_since(cutoff)
        logger.info("sessões ociosas apagadas: %d (anteriores a %s)", removed, cutoff.isoformat())
        return removed
