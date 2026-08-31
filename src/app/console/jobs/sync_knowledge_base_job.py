import logging

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
