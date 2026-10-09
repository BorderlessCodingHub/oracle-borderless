from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel
from src.support.core.settings import settings


class LessonChunkModel(BaseModel, HasUUID, HasTimestamps):
    __tablename__ = "lesson_chunks"

    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.uuid", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )

    # Mesmo motivo do DocumentChunkModel: o índice nasce na migration por SQL
    # cru, e sem esta declaração o autogenerate do Alembic o veria como índice
    # a remover em todo `alembic check`.
    __table_args__ = (
        Index(
            "ix_lesson_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
