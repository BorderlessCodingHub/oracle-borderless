from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from src.domain.documents.entities.document import Document
from src.domain.documents.mappers import DocumentMapper
from src.domain.documents.models.document import DocumentModel
from src.support.core.context import CurrentAsyncSessionContext


class DocumentRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def get_by_notion_page_id(self, page_id: str) -> Document | None:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.notion_page_id == page_id)
        )
        model = result.scalar_one_or_none()
        return DocumentMapper.to_entity(model) if model else None

    async def get_by_id(self, document_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.uuid == document_id)
        )
        model = result.scalar_one_or_none()
        return DocumentMapper.to_entity(model) if model else None

    async def upsert(self, document: Document) -> Document:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.notion_page_id == document.notion_page_id)
        )
        model = result.scalar_one_or_none()
        attrs = DocumentMapper.to_model_attrs(document)
        if model is None:
            model = DocumentModel(**attrs)
            self.session.add(model)
        else:
            for key in (
                "title",
                "content",
                "source_url",
                "status",
                "deleted_at",
                "last_edited_time",
                "kb_root_page_id",
                "kb_section",
            ):
                setattr(model, key, attrs[key])
        await self.session.flush()
        await self.session.refresh(model)
        return DocumentMapper.to_entity(model)

    async def list_all(self) -> list[Document]:
        """Todos os documentos, incluindo soft-deleted (para o sync diferenciar)."""
        result = await self.session.execute(select(DocumentModel))
        return [DocumentMapper.to_entity(m) for m in result.scalars().all()]

    async def soft_delete_by_page_id(self, page_id: str, when: datetime) -> None:
        """Marca como removido (saiu do escopo aprovado). Retrieval já ignora deleted_at."""
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.notion_page_id == page_id)
        )
        model = result.scalar_one_or_none()
        if model is not None:
            model.deleted_at = when
            await self.session.flush()

    async def list_sections(self) -> list[str]:
        """Seções distintas dos documentos ativos, ordenadas."""
        result = await self.session.execute(
            select(DocumentModel.kb_section)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_section.is_not(None),
            )
            .distinct()
        )
        return sorted({(s or "").strip() for s in result.scalars().all() if (s or "").strip()})

    async def count_active(self) -> int:
        """Documentos aprovados e não removidos — exatamente o que o oráculo serve."""
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentModel)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one()

    async def count_archived(self) -> int:
        """Documentos removidos por soft-delete na reconciliação do sync."""
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentModel)
            .where(
                DocumentModel.deleted_at.is_not(None),
            )
        )
        return result.scalar_one()

    async def count_by_root(self) -> dict[str, int]:
        """Documentos ativos agrupados por procedência (`kb_root_page_id`).

        Diagnóstico, não escopo (ADR-0015): responde "o oráculo está mesmo
        lendo o que eu liberei?" no `knowledge:roots`. Documento sem
        procedência gravada entra sob a chave vazia.
        """
        result = await self.session.execute(
            select(DocumentModel.kb_root_page_id, func.count())
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
            )
            .group_by(DocumentModel.kb_root_page_id)
        )
        # Acumula em vez de sobrescrever: o Postgres agrupa NULL e "" como
        # linhas distintas, e uma comprehension ingênua faria uma pisar na
        # outra silenciosamente se as duas aparecessem no resultado.
        counts: dict[str, int] = {}
        for root, count in result.all():
            key = root or ""
            counts[key] = counts.get(key, 0) + count
        return counts
