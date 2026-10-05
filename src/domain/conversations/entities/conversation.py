from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Conversation:
    """Entidade de domínio de uma conversa. Pura — sem SQLAlchemy."""

    uuid: UUID
    user_email: str | None
    title: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    # "chat" | "navigate" | "mentor" | None (linhas anteriores à 0014 já backfilladas).
    mode: str | None = None
