from uuid import UUID

from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.support.agent.ports import KnowledgeSnippet
from src.support.clients.embeddings.embeddings_client import EmbeddingsClient


class SearchLessonAction:
    """RAG com escopo de aula: embed da query → top-k dentro daquela aula.

    Devolve a distância junto com cada trecho — o chamador usa a menor delas
    para classificar a cobertura da pergunta (spec §9.2).
    """

    def __init__(self, embeddings: EmbeddingsClient, chunk_repo=None) -> None:
        self.embeddings = embeddings
        self.chunks = chunk_repo or LessonChunkRepository()
        self.last_query_embedding: list[float] | None = None

    async def execute(
        self, lesson_id: UUID, query: str, top_k: int | None = None
    ) -> list[tuple[KnowledgeSnippet, float]]:
        vector = await self.embeddings.embed_query(query)
        # Guardado para o trace: o embedding da pergunta já foi calculado aqui,
        # e descartá-lo obrigaria a re-embedar o backlog inteiro quando formos
        # agrupar as perguntas (spec §9.1). Se houver mais de uma busca no
        # turno, a última vence — é a que reflete a pergunta refinada.
        self.last_query_embedding = vector
        return await self.chunks.search_similar(lesson_id, vector, top_k=top_k)
