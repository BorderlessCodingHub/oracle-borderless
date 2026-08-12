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
        roots = settings.kb_root_page_ids
        if not roots:
            # Guarda deliberada, não simplificar: `DocumentModel.kb_root_page_id
            # == None` compila para `WHERE kb_root_page_id IS NULL`, que combina
            # exatamente com os documentos sem procedência — o conjunto que este
            # filtro existe para excluir. `IN` já exclui NULL naturalmente, mas a
            # guarda continua necessária: `IN ()` sem roots seria SQL inválido, e
            # sem roots a leitura precisa degradar para "sem conhecimento" em vez
            # de expor tudo.
            return []
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
                # Escopo como invariante de leitura (ADR-0012): documento de outro
                # root — ou sem procedência — não é servido, mesmo sem sync.
                DocumentModel.kb_root_page_id.in_(roots),
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
        roots = settings.kb_root_page_ids
        if not roots:
            return None  # mesma degradação fail-closed do search_similar

        distance = DocumentChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(distance)
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_root_page_id.in_(roots),
            )
            .order_by(distance)
            .limit(1)
        )
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(value) if value is not None else None

    async def count_in_scope(self) -> int:
        """Chunks de documentos ativos e aprovados do conjunto de roots configurado.

        Mesmo filtro de `search_similar`, sem o corte por distância — é a
        contagem "quanto conhecimento o oráculo tem para servir", não uma
        busca por uma pergunta específica. Sem roots configurados, degrada
        para zero (mesma convenção fail-closed das outras leituras).
        """
        roots = settings.kb_root_page_ids
        if not roots:
            return 0
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentChunkModel)
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_root_page_id.in_(roots),
            )
        )
        return result.scalar_one()
