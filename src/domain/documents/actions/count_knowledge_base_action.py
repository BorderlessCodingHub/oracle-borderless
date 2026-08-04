from sqlalchemy import func, select

from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
from src.domain.documents.models.document import DocumentModel
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.domain.observability.dtos.ops_overview import KnowledgeCounts
from src.support.core.context import CurrentAsyncSessionContext


class CountKnowledgeBaseAction:
    """Contagens da base para a página de ops. Fronteira do subdomínio documents:
    quem quer esses números compõe esta Action, não o repositório."""

    def __init__(self, sections=None) -> None:
        self.session = CurrentAsyncSessionContext.get()
        self.sections = sections or ListKnowledgeSectionsAction()

    async def execute(self) -> KnowledgeCounts:
        active = await self.session.scalar(
            select(func.count())
            .select_from(DocumentModel)
            .where(DocumentModel.deleted_at.is_(None), DocumentModel.status == "approved")
        )
        archived = await self.session.scalar(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.deleted_at.is_not(None))
        )
        chunks = await self.session.scalar(select(func.count()).select_from(DocumentChunkModel))
        return KnowledgeCounts(
            documents_active=active or 0,
            documents_archived=archived or 0,
            chunks=chunks or 0,
            sections=await self.sections.execute(),
        )
