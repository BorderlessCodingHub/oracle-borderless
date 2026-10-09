from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class LessonModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    __tablename__ = "lessons"

    platform_video_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    program_slug: Mapped[str] = mapped_column(String(255), index=True)
    module_slug: Mapped[str] = mapped_column(String(255))
    video_slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_ref: Mapped[str] = mapped_column(String(255))
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(String(20), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
