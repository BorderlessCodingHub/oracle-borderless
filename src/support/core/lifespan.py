"""LifespanManager — centraliza startup/shutdown da aplicação FastAPI."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from src.support.core.database import dispose_engines
from src.support.core.logging import configure_logging
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


class LifespanManager:
    """Orquestra warmup e teardown: logging, scheduler, pools de DB."""

    def __init__(self) -> None:
        self._scheduler = None

    async def startup(self) -> None:
        configure_logging()
        logger.info("Iniciando %s (env=%s)", settings.APP_NAME, settings.ENVIRONMENT)

        self._validate_kb_root_env()

        if settings.ENABLE_SCHEDULER:
            self._boot_scheduler()

    @staticmethod
    def _validate_kb_root_env() -> None:
        """Detecta deploy com a env var antiga (ou um `_ID`/`_IDS` digitado errado).

        `NOTION_KB_ROOT_PAGE_ID` (singular, ADR-0011) foi substituído por
        `NOTION_KB_ROOT_PAGE_IDS` (CSV, ADR-0014). Como o pydantic-settings
        ignora chave desconhecida (`extra="ignore"`), um deploy que ainda
        exporta só o nome antigo sobe normal, com `kb_root_page_ids` vazio —
        e daí o oráculo responde "não encontrei informações" para TODA
        pergunta, sem nada que ligue o sintoma à causa. Falhar aqui, no boot,
        é melhor que esse silêncio.
        """
        if settings.NOTION_KB_ROOT_PAGE_ID and not settings.kb_root_page_ids:
            raise RuntimeError(
                "NOTION_KB_ROOT_PAGE_ID está definido, mas foi substituído por "
                "NOTION_KB_ROOT_PAGE_IDS (lista separada por vírgula) — ver "
                "ADR-0014. Atualize a env var; a aplicação não sobe sem escopo "
                "de KB configurado."
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
