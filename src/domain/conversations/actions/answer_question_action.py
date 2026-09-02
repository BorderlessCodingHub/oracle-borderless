import logging
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.conversations.repositories.conversation_repository import ConversationRepository
from src.domain.conversations.repositories.message_repository import MessageRepository
from src.domain.conversations.services.conversation_access_policy import ConversationAccessPolicy
from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply
from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.ports import AgentStreamChunk, TurnDependencies, TurnGraphPort, TurnSignals
from src.support.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

_TITLE_MAX = 80


class _NearestDistance:
    """Adapta o repositório de chunks ao NearestDistancePort. Só o nó de recusa
    usa, e só para o trace."""

    def __init__(self, search: SearchKnowledgeBaseAction, chunks: DocumentChunkRepository) -> None:
        self._search = search
        self._chunks = chunks

    async def execute(self, query: str) -> float | None:
        vector = await self._search.embeddings.embed_query(query)
        return await self._chunks.nearest_distance(vector)


class AnswerQuestionAction:
    """Caso de uso do oráculo: resolve a conversa, grava a mensagem do usuário,
    carrega a recência e entrega o turno ao grafo.

    O pipeline de decisão (gate, retrieval, limiar, recusa, resposta) vive no
    grafo, em support/agent/graph/ — aqui ficou só o que é persistência e
    composição. Ver ADR-0016.
    """

    def __init__(
        self,
        graph: TurnGraphPort,
        search: SearchKnowledgeBaseAction,
        sections=None,
        chunks=None,
    ) -> None:
        self.graph = graph
        self.search = search
        self.sections = sections or ListKnowledgeSectionsAction()
        self.chunks = chunks or DocumentChunkRepository()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    async def execute(
        self, question: str, conversation_id: UUID | None, user_email: str | None
    ) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]:
        now = datetime.now(timezone.utc)
        draft = TurnTraceDraft(question=question, user_email=user_email)

        if conversation_id is None:
            conversation = await self.conversations.create(
                Conversation(
                    uuid=uuid7(),
                    user_email=user_email,
                    title=question[:_TITLE_MAX],
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        else:
            conversation = await self.conversations.get_by_id(conversation_id)
            if conversation is None:
                raise NotFoundError(f"conversa {conversation_id} não encontrada")
            ConversationAccessPolicy.assert_can_access(conversation, user_email)

        # Recência = turnos ANTERIORES (antes de gravar a pergunta atual, que já
        # vai ao grafo como `question`).
        history = await self.messages.load_recent(conversation.uuid)
        draft.history_messages = len(history)
        draft.history_tokens_est = sum(max(1, len(m.content) // 4) for m in history)

        await self.messages.append(
            Message(
                uuid=uuid7(),
                conversation_id=conversation.uuid,
                role="user",
                content=question,
                created_at=now,
            )
        )

        signals = TurnSignals()
        draft.signals = signals
        deps = TurnDependencies(
            search=self.search,
            sections=self.sections,
            refusal=build_out_of_scope_reply,
            nearest=_NearestDistance(self.search, self.chunks),
        )

        # O await abaixo executa gate e retrieval AQUI, com a sessão viva. Depois
        # dele o gerador só produz token de LLM e tool HTTP — ver spec, seção 5.
        stream = await self.graph.start(question, history, deps, signals)
        return conversation.uuid, stream, draft
