from datetime import datetime, timezone
from uuid import UUID

from uuid6 import uuid7

from src.domain.conversations.dtos.opened_turn import OpenedTurn
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.conversations.repositories.conversation_repository import ConversationRepository
from src.domain.conversations.repositories.message_repository import MessageRepository
from src.domain.conversations.services.conversation_access_policy import ConversationAccessPolicy
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.ports import TurnSignals

_TITLE_MAX = 80


class OpenTurnAction:
    """Abre um turno do oráculo: resolve a conversa, grava a pergunta, carrega a
    recência e prepara os coletores do trace. Roda no escopo da sessão do
    request — tudo que precisa virar status HTTP (404 da policy, falha ao gravar)
    acontece aqui, antes do primeiro byte do corpo SSE.

    NÃO monta `deps` nem dispara o grafo: isso é `RunTurnAction`, no corpo SSE,
    dentro de um escopo de sessão próprio (ADR-0020).
    """

    def __init__(self) -> None:
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()

    async def execute(
        self,
        question: str,
        conversation_id: UUID,
        user_email: str | None,
        mode: str = "chat",
        locale: str = "pt-BR",
        lesson_id: str | None = None,
    ) -> OpenedTurn:
        now = datetime.now(timezone.utc)
        draft = TurnTraceDraft(question=question, user_email=user_email)

        # ADR-0021: o id vem do cliente (config.configurable.thread_id) — find-or-create.
        # Conhecido e do usuário → continua; desconhecido → nasce com ESSE id; de outro
        # usuário → a policy responde 404 (nunca revela que existe).
        conversation = await self.conversations.get_by_id(conversation_id)
        if conversation is None:
            conversation = await self.conversations.create(
                Conversation(
                    uuid=conversation_id,
                    user_email=user_email,
                    title=question[:_TITLE_MAX],
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        else:
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
        return OpenedTurn(
            conversation_id=conversation.uuid,
            question=question,
            history=history,
            draft=draft,
            signals=signals,
            mode=mode,
            locale=locale,
            lesson_id=lesson_id,
        )
