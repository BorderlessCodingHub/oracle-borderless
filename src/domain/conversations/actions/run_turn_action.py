from src.domain.conversations.dtos.opened_turn import OpenedTurn
from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply
from src.domain.documents.actions.list_knowledge_sections_action import ListKnowledgeSectionsAction
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.support.agent.ports import TurnDependencies, TurnGraphPort, TurnRun
from src.support.clients.embeddings.embeddings_client import EmbeddingsClient


class _NearestDistance:
    """Adapta o repositório de chunks ao NearestDistancePort. Só o nó de recusa
    usa, e só para o trace."""

    def __init__(self, search: SearchKnowledgeBaseAction, chunks: DocumentChunkRepository) -> None:
        self._search = search
        self._chunks = chunks

    async def execute(self, query: str) -> float | None:
        vector = await self._search.embeddings.embed_query(query)
        return await self._chunks.nearest_distance(vector)


class RunTurnAction:
    """Dispara o grafo para um turno já aberto. Monta os `deps` AQUI, no escopo
    de sessão em que for chamada: os repositórios capturam a sessão do
    ContextVar no __init__ (regra 3), e a fase 1 do grafo roda no corpo SSE,
    fora da sessão do request (ADR-0020). Construir isto no request deixaria os
    repositórios com uma sessão já fechada.

    Síncrona: só composição. Quem itera `prelude()` (dentro do escopo) e
    `stream()` (fora) é o controller.
    """

    def __init__(self, graph: TurnGraphPort, embeddings: EmbeddingsClient) -> None:
        self.graph = graph
        self.embeddings = embeddings

    def execute(self, turn: OpenedTurn, extra_config: dict | None = None) -> TurnRun:
        search = SearchKnowledgeBaseAction(embeddings=self.embeddings)
        deps = TurnDependencies(
            search=search,
            sections=ListKnowledgeSectionsAction(),
            refusal=build_out_of_scope_reply,
            nearest=_NearestDistance(search, DocumentChunkRepository()),
        )
        return self.graph.run(
            turn.question, turn.history, deps, turn.signals,
            mode=turn.mode, locale=turn.locale, extra_config=extra_config,
            lesson_id=turn.lesson_id,
        )
