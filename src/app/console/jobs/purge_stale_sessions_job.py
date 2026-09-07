import logging

from src.domain.users.actions.purge_stale_sessions_action import PurgeStaleSessionsAction
from src.support.core.scheduling import Job

logger = logging.getLogger(__name__)


class PurgeStaleSessionsJob(Job):
    """Apaga sessões do oráculo sem validação há mais de 7 dias (ADR-0018).

    Idempotente: rodar duas vezes apaga zero na segunda. A `Job.execute` já
    provê sessão + advisory lock + tracking.
    """

    async def action(self) -> None:
        removed = await PurgeStaleSessionsAction().execute()
        logger.info("PurgeStaleSessionsJob: %d sessões apagadas", removed)
