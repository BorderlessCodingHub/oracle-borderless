from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.models.lesson_chunk import LessonChunkModel


class LessonChunkMapper:
    @staticmethod
    def to_entity(model: LessonChunkModel) -> LessonChunk:
        return LessonChunk(
            uuid=model.uuid,
            lesson_id=model.lesson_id,
            ordinal=model.ordinal,
            content=model.content,
            start_seconds=model.start_seconds,
            end_seconds=model.end_seconds,
            embedding=list(model.embedding) if model.embedding is not None else None,
        )

    @staticmethod
    def to_model_attrs(entity: LessonChunk) -> dict:
        return {
            "uuid": entity.uuid,
            "lesson_id": entity.lesson_id,
            "ordinal": entity.ordinal,
            "content": entity.content,
            "start_seconds": entity.start_seconds,
            "end_seconds": entity.end_seconds,
            "embedding": entity.embedding,
        }
