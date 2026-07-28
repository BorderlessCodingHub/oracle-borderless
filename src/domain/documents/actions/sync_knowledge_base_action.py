import logging
from datetime import datetime, timezone

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.dtos.sync_report import SyncReport
from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


def _is_stale(notion_ts: datetime | None, stored_ts: datetime | None) -> bool:
    """Precisa reingerir? Sim se nunca vimos o timestamp, ou se o Notion é mais novo."""
    if stored_ts is None or notion_ts is None:
        return True
    return notion_ts > stored_ts


class SyncKnowledgeBaseAction:
    """Sincroniza toda a base aprovada do Notion no pgvector — bootstrap e refresh.

    Idempotente e incremental: só reingere páginas novas ou editadas
    (`last_edited_time`), e remove (soft-delete + limpa chunks) as que saíram do
    escopo aprovado. Composição: NotionClient (curadoria embutida) + IngestDocumentAction.
    """

    def __init__(
        self,
        notion,
        ingest: IngestDocumentAction,
        documents=None,
        chunks=None,
        atomic=None,
    ) -> None:
        self.notion = notion
        self.ingest = ingest
        self.documents = documents or DocumentRepository()
        self.chunks = chunks or DocumentChunkRepository()
        # Fronteira transacional por página: savepoint real em produção (rollback
        # só da página que falha), injetável nos testes (nullcontext).
        self._atomic = atomic or self._savepoint

    def _savepoint(self):
        return CurrentAsyncSessionContext.get().begin_nested()

    async def execute(self, force: bool = False, limit: int | None = None) -> SyncReport:
        approved = await self.notion.list_approved_pages()
        root_page_id = settings.NOTION_KB_ROOT_PAGE_ID or ""
        existing = {doc.notion_page_id: doc for doc in await self.documents.list_all()}
        report = SyncReport(total_approved=len(approved))

        # Run limitado = bootstrap parcial: ingere até `limit` páginas NOVAS
        # (pulando as já feitas, para blocos repetidos AVANÇAREM) e NÃO
        # reconcilia remoções (senão apagaria tudo fora do recorte).
        partial = limit is not None

        approved_ids = set()
        for page in approved:
            approved_ids.add(page.id)
            if partial and report.ingested >= limit:
                break  # orçamento de ingestão do bloco esgotado
            current = existing.get(page.id)
            needs_ingest = (
                force
                or current is None
                or current.deleted_at is not None
                or _is_stale(page.last_edited_time, current.last_edited_time)
            )
            if needs_ingest:
                try:
                    async with self._atomic():
                        full = await self.notion.get_page(page.id)
                        full.section = page.section
                        await self.ingest.execute(
                            NotionPageMapper.to_document(full, root_page_id)
                        )
                    report.ingested += 1
                except Exception as exc:  # falha de uma página não derruba o bloco
                    logger.warning(
                        "sync: falha ao ingerir %s (%s): %s", page.id, page.title, exc
                    )
                    report.failed += 1
            else:
                report.skipped += 1

        if not partial:
            now = datetime.now(timezone.utc)
            for page_id, doc in existing.items():
                if page_id not in approved_ids and doc.deleted_at is None:
                    await self.documents.soft_delete_by_page_id(page_id, now)
                    await self.chunks.replace_for_document(doc.uuid, [])
                    report.removed += 1

        return report
