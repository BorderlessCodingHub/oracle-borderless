from datetime import datetime, timezone
from uuid import UUID

from uuid6 import uuid7

from src.domain.conversations.entities.message import Message
from src.domain.conversations.repositories.message_repository import MessageRepository
from src.domain.shared.value_objects.citation import Citation


class AppendAssistantMessageAction:
    """Persiste a resposta do oráculo após o streaming terminar. Chamada dentro
    de run_in_async_session (sessão própria, fora do request)."""

    def __init__(self) -> None:
        self.messages = MessageRepository()

    async def execute(
        self,
        conversation_id: UUID,
        content: str,
        citations: list[Citation],
        navigation: dict | None = None,
    ) -> None:
        await self.messages.append(
            Message(
                uuid=uuid7(),
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                created_at=datetime.now(timezone.utc),
                sources=list(citations) if citations else None,
                navigation=navigation,
            )
        )
