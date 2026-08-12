import logging

from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.actions.sync_knowledge_base_action import SyncKnowledgeBaseAction
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.scheduling import Job

logger = logging.getLogger(__name__)


class SyncKnowledgeBaseJob(Job):
    """Refresh incremental da base de conhecimento (Notion → pgvector).

    Idempotente: só reingere páginas novas/editadas e remove as que saíram do
    escopo aprovado. A `Job.execute` já provê sessão + advisory lock + tracking.
    """

    async def action(self) -> None:
        result = await SyncKnowledgeBaseAction(
            notion=NotionClient(),
            ingest=IngestDocumentAction(embeddings=get_embeddings_client()),
        ).execute()
        logger.info("SyncKnowledgeBaseJob: %s", result)
        await self._warn_on_drift(DetectKbRootDriftAction())

    @staticmethod
    async def _warn_on_drift(action) -> None:
        """Avisa quando a allowlist de roots diverge do que o Notion enxerga.

        É o sinal que substitui o aviso humano. Falha aqui nunca derruba o
        sync: o refresh da base já aconteceu e vale mais que o diagnóstico.
        """
        try:
            drift = await action.execute()
        except Exception:  # observabilidade não derruba o job
            logger.warning("não foi possível checar drift de roots", exc_info=True)
            return
        for page in drift.unlisted:
            logger.warning(
                "root liberado no Notion e fora de NOTION_KB_ROOT_PAGE_IDS: %s (%s)",
                page.title,
                page.id,
            )
        # Direção mais perigosa: root que ESTÁ na allowlist e a integração não
        # alcança mais — permissão revogada, página movida, ou id errado na
        # env var. Ao contrário de `unlisted` (o oráculo lê menos do que
        # podia), esta é a que precede perda de conteúdo servível.
        for root_id in drift.missing:
            logger.warning(
                "root em NOTION_KB_ROOT_PAGE_IDS que o Notion não enxerga mais: %s "
                "— verifique permissão revogada, página movida, ou id errado na env var",
                root_id,
            )
