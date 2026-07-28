from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class DocumentModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    __tablename__ = "documents"

    notion_page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(20), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_edited_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kb_root_page_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    kb_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
