from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class ConversationModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    __tablename__ = "conversations"

    user_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_conversations_user_email_mode", "user_email", "mode"),)
