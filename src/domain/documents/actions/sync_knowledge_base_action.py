import logging
from datetime import datetime, timezone

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.dtos.sync_report import SyncReport
from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.utils.notion_ids import normalize_page_id

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
                # Auto-cura: se a provenência gravada não bate com o root sob o
                # qual a página foi descoberta agora (ex.: coluna NULL logo após
                # a migração 0004, ou página que mudou de root), reingere mesmo
                # sem --force. Sem isso, um sync incremental nunca re-stampa
                # `kb_root_page_id` e o retrieval filtrado por root passa a
                # devolver [] pra sempre.
                or (
                    current is not None
                    and normalize_page_id(current.kb_root_page_id)
                    != normalize_page_id(page.kb_root_page_id)
                )
            )
            if needs_ingest:
                try:
                    async with self._atomic():
                        full = await self.notion.get_page(page.id)
                        full.section = page.section
                        await self.ingest.execute(
                            NotionPageMapper.to_document(full, page.kb_root_page_id or "")
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
                if doc.deleted_at is not None:
                    continue
                # Único motivo de saída de escopo observável aqui: a página não
                # apareceu em nenhuma travessia desta rodada. Um root que o Yuri
                # despublicou não é mais descoberto por `list_approved_pages`,
                # então suas páginas somem de `approved_ids` por AUSÊNCIA da
                # travessia — não porque comparamos a procedência gravada contra
                # uma lista. Essa segunda comparação já existiu aqui e era sempre
                # inalcançável; não reintroduza. Descoberta vazia não chega até
                # aqui: `list_approved_pages` aborta antes (ADR-0015).
                left_scope = page_id not in approved_ids
                if left_scope:
                    await self.documents.soft_delete_by_page_id(page_id, now)
                    await self.chunks.replace_for_document(doc.uuid, [])
                    report.removed += 1

        return report
