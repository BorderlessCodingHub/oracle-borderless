from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel
from src.support.core.settings import settings


class DocumentChunkModel(BaseModel, HasUUID, HasTimestamps):
    __tablename__ = "document_chunks"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.uuid", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )

    # Índice ANN criado na migration 0001 via SQL cru. Declarado aqui para que o
    # autogenerate do Alembic o reconheça como parte do metadata — sem isso ele
    # aparece como "índice a remover" em todo `alembic check`.
    __table_args__ = (
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
