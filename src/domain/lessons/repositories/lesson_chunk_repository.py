from uuid import UUID

from sqlalchemy import delete, func, select

from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.mappers.lesson_chunk_mapper import LessonChunkMapper
from src.domain.lessons.models.lesson_chunk import LessonChunkModel
from src.support.core.context import CurrentAsyncSessionContext


class LessonChunkRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def replace_for_lesson(self, lesson_id: UUID, chunks: list[LessonChunk]) -> None:
        await self.session.execute(
            delete(LessonChunkModel).where(LessonChunkModel.lesson_id == lesson_id)
        )
        for chunk in chunks:
            self.session.add(LessonChunkModel(**LessonChunkMapper.to_model_attrs(chunk)))
        await self.session.flush()

    async def count_for_lesson(self, lesson_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LessonChunkModel)
            .where(LessonChunkModel.lesson_id == lesson_id)
        )
        return result.scalar_one()
