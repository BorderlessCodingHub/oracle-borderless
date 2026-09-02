"""LifespanManager — centraliza startup/shutdown da aplicação FastAPI."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from src.support.core.database import dispose_engines
from src.support.core.logging import configure_logging
from src.support.core.settings import settings
from src.support.observability.langsmith import configure_langsmith

logger = logging.getLogger(__name__)


class LifespanManager:
    """Orquestra warmup e teardown: logging, scheduler, pools de DB."""

    def __init__(self) -> None:
        self._scheduler = None

    async def startup(self) -> None:
        configure_logging()
        logger.info("Iniciando %s (env=%s)", settings.APP_NAME, settings.ENVIRONMENT)

        configure_langsmith()

        self._validate_kb_root_env()

        if settings.ENABLE_SCHEDULER:
            self._boot_scheduler()

    @staticmethod
    def _validate_kb_root_env() -> None:
        """Detecta deploy que ainda acha que controla o escopo da KB por env var.

        Desde o ADR-0015 o escopo é o que a integração do Notion enxerga —
        nenhum código lê essas variáveis para decidir escopo. Um deploy que
        ainda as exporta subiria normal, e a pessoa que as configurou acharia
        que restringiu a base quando não restringiu nada. Falhar no boot é
        melhor que essa crença silenciosa.
        """
        stale = [
            name
            for name in ("NOTION_KB_ROOT_PAGE_IDS", "NOTION_KB_ROOT_PAGE_ID")
            if (getattr(settings, name, None) or "").strip()
        ]
        if stale:
            raise RuntimeError(
                f"{', '.join(stale)} está definido, mas o escopo da base de "
                "conhecimento deixou de vir de variável de ambiente: agora é o "
                "que a integração do Notion enxerga (ADR-0015). Remova a "
                "variável do ambiente; para mudar o escopo, mude o "
                "compartilhamento no Notion."
            )

    def _boot_scheduler(self) -> None:
        # Import tardio: só carrega o scheduler/registro quando habilitado.
        from src.app.console.schedule import schedule
        from src.support.core.scheduling import JobScheduler

        self._scheduler = JobScheduler()
        self._scheduler.register(schedule)
        self._scheduler.start()

    async def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown()
        await dispose_engines()
        logger.info("%s encerrado.", settings.APP_NAME)


@asynccontextmanager
async def lifespan(app) -> AsyncIterator[None]:
    """Lifespan para `FastAPI(lifespan=lifespan)`."""
    manager = LifespanManager()
    await manager.startup()
    try:
        yield
    finally:
        await manager.shutdown()
