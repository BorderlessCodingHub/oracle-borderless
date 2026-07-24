from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID

from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.conversations.repositories.conversation_repository import ConversationRepository
from src.domain.conversations.repositories.message_repository import MessageRepository
from src.domain.conversations.services.conversation_access_policy import ConversationAccessPolicy
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.support.agent.ports import AgentStreamChunk, OracleEnginePort, RetrievalGatePort
from src.support.core.exceptions import NotFoundError

_TITLE_MAX = 80


class AnswerQuestionAction:
    """Caso de uso do oráculo com memória episódica: resolve a conversa, grava a
    mensagem do usuário, carrega a recência, recupera a base (RAG clássico) e
    delega o streaming ao motor. Composição de Actions/repos + engine."""

    def __init__(
        self, engine: OracleEnginePort, search: SearchKnowledgeBaseAction, gate: RetrievalGatePort
    ) -> None:
        self.engine = engine
        self.search = search
        self.gate = gate
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    async def execute(
        self, question: str, conversation_id: UUID | None, user_email: str | None
    ) -> tuple[UUID, AsyncIterator[AgentStreamChunk]]:
        now = datetime.now(timezone.utc)

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
        # vai ao engine como `question`).
        history = await self.messages.load_recent(conversation.uuid)

        decision = await self.gate.decide(question, history)

        await self.messages.append(
            Message(
                uuid=uuid7(),
                conversation_id=conversation.uuid,
                role="user",
                content=question,
                created_at=now,
            )
        )

        if decision.retrieve:
            knowledge = await self.search.execute(decision.search_query)  # query reescrita
        else:
            knowledge = []  # nada injetado — sem poluição de contexto

        return conversation.uuid, self.engine.stream_answer(question, history, knowledge)
