from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.shared.value_objects.citation import Citation


@dataclass
class Message:
    """Um turno da conversa. `sources` só é preenchido em mensagens do assistente."""

    uuid: UUID
    conversation_id: UUID
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime
    sources: list[Citation] | None = None
    navigation: dict | None = None
