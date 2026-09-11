from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import HasUUID
from src.support.core.models.base_model import BaseModel


class TurnTraceModel(BaseModel, HasUUID):
    __tablename__ = "agent_traces"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.uuid", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.uuid", ondelete="SET NULL"), nullable=True
    )
    user_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    question: Mapped[str] = mapped_column(Text)

    history_messages: Mapped[int] = mapped_column(Integer, default=0)
    history_tokens_est: Mapped[int] = mapped_column(Integer, default=0)

    gate_retrieve: Mapped[bool] = mapped_column(Boolean, index=True)
    gate_search_query: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gate_degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_ms: Mapped[int] = mapped_column(Integer, default=0)

    retrieval_ran: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieval_top_k: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_kept: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_best_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_threshold: Mapped[float] = mapped_column(Float, default=0.0)
    retrieval_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    outcome: Mapped[str] = mapped_column(String(16), index=True)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citations_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    langsmith_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    intent: Mapped[str | None] = mapped_column(String(16), nullable=True)
    navigation_called: Mapped[bool] = mapped_column(Boolean, default=False)
    navigation_access: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_agent_traces_created_at", "created_at"),)
