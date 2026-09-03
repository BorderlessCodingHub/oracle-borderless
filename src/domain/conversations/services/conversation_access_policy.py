"""Regra de acesso a conversa (ADR-0017).

Domain Service (regra sem dono natural). 404 — nunca 403: não revelar que a
conversa existe. Conversa órfã (user_email null, período pré-auth) também é
404 para todos (spec §4.6).
"""

from src.domain.conversations.entities.conversation import Conversation
from src.support.core.exceptions import NotFoundError


class ConversationAccessPolicy:
    @staticmethod
    def assert_can_access(conversation: Conversation, user_email: str | None) -> None:
        if conversation.user_email != user_email:
            raise NotFoundError("conversa não encontrada")
