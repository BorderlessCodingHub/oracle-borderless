from uuid import UUID

from sqlalchemy import delete, func, select

from src.domain.documents.entities.document_chunk import DocumentChunk
from src.domain.documents.mappers import DocumentChunkMapper
from src.domain.documents.models.document import DocumentModel
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.settings import settings


class DocumentChunkRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def replace_for_document(self, document_id: UUID, chunks: list[DocumentChunk]) -> None:
        await self.session.execute(
            delete(DocumentChunkModel).where(DocumentChunkModel.document_id == document_id)
        )
        for chunk in chunks:
            self.session.add(DocumentChunkModel(**DocumentChunkMapper.to_model_attrs(chunk)))
        await self.session.flush()

    async def search_similar(
        self, embedding: list[float], top_k: int | None = None
    ) -> list[KnowledgeSnippet]:
        limit = top_k if top_k is not None else settings.RAG_TOP_K
        distance = DocumentChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(
                DocumentChunkModel.content,
                DocumentModel.title,
                DocumentModel.source_url,
                DocumentModel.notion_page_id,
            )
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                # Sem limiar, top-k sempre devolve algo: pergunta fora do assunto
                # recuperaria os vizinhos menos distantes e viraria contexto.
                distance <= settings.RAG_MAX_DISTANCE,
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            KnowledgeSnippet(
                content=row.content,
                citation=Citation(
                    source_type="notion",
                    title=row.title,
                    url=row.source_url,
                    snippet=row.content[:200],
                    page_id=row.notion_page_id,
                ),
            )
            for row in rows
        ]

    async def nearest_distance(self, embedding: list[float]) -> float | None:
        """Distância do chunk mais próximo **ignorando o limiar**.

        Serve o trace no caminho de recusa: `search_similar` filtra pelo limiar
        dentro do SQL, então quando ela devolve vazio não se sabe se faltou 0,01
        ou 0,3. Uma query de índice, chamada só quando nada passou — turno que
        recusa não chamou o LLM e tem folga de sobra.
        """
        distance = DocumentChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(distance)
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
            )
            .order_by(distance)
            .limit(1)
        )
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(value) if value is not None else None

    async def count_in_scope(self) -> int:
        """Chunks de documentos ativos e aprovados — quanto o oráculo tem para servir.

        Mesmo filtro do `search_similar`, sem o corte por distância. Desde o
        ADR-0015 não há filtro por procedência: o escopo é o que a integração
        do Notion enxerga, aplicado na descoberta e na reconciliação.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentChunkModel)
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
            )
        )
        return result.scalar_one()
