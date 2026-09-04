from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class UserSessionModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    """Persistência da sessão do oráculo (ADR-0018). Só mapeamento."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    platform_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_platform_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
