from dataclasses import dataclass
from uuid import UUID


@dataclass
class LessonChunk:
    """Trecho de uma aula, com a janela de tempo de onde ele veio."""

    uuid: UUID
    lesson_id: UUID
    ordinal: int
    content: str
    start_seconds: float
    end_seconds: float
    embedding: list[float] | None = None
