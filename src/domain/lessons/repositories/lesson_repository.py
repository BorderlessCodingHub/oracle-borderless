from sqlalchemy import select

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.mappers.lesson_mapper import LessonMapper
from src.domain.lessons.models.lesson import LessonModel
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.exceptions import NotFoundError

# Campos que vêm do catálogo da plataforma. O estado de transcrição NÃO está
# aqui de propósito: re-sincronizar o catálogo não pode jogar fora o trabalho
# de transcrição já feito.
_CATALOG_FIELDS = (
    "program_slug",
    "module_slug",
    "video_slug",
    "title",
    "duration_seconds",
    "provider",
    "provider_ref",
)


class LessonRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def _model_by_video_id(self, video_id: str) -> LessonModel | None:
        result = await self.session.execute(
            select(LessonModel).where(LessonModel.platform_video_id == video_id)
        )
        return result.scalar_one_or_none()

    async def get_by_platform_video_id(self, video_id: str) -> Lesson | None:
        model = await self._model_by_video_id(video_id)
        return LessonMapper.to_entity(model) if model else None

    async def upsert_from_catalog(self, lesson: Lesson) -> Lesson:
        model = await self._model_by_video_id(lesson.platform_video_id)
        attrs = LessonMapper.to_model_attrs(lesson)
        if model is None:
            model = LessonModel(**attrs)
            self.session.add(model)
        else:
            for key in _CATALOG_FIELDS:
                setattr(model, key, attrs[key])
        await self.session.flush()
        await self.session.refresh(model)
        return LessonMapper.to_entity(model)

    async def save(self, lesson: Lesson) -> Lesson:
        model = await self._model_by_video_id(lesson.platform_video_id)
        if model is None:
            raise NotFoundError(f"aula {lesson.platform_video_id} não existe")
        for key, value in LessonMapper.to_model_attrs(lesson).items():
            if key != "uuid":
                setattr(model, key, value)
        await self.session.flush()
        await self.session.refresh(model)
        return LessonMapper.to_entity(model)

    async def list_pending(self, program_slug: str, max_attempts: int) -> list[Lesson]:
        """Aulas que o lote deve processar: nunca transcritas, ou que falharam e
        ainda têm tentativa. `transcribing` fica de fora — é claim de outra
        execução."""
        result = await self.session.execute(
            select(LessonModel)
            .where(
                LessonModel.program_slug == program_slug,
                LessonModel.transcript_status.in_(
                    [str(TranscriptStatus.PENDING), str(TranscriptStatus.FAILED)]
                ),
                LessonModel.attempts < max_attempts,
            )
            .order_by(LessonModel.created_at)
        )
        return [LessonMapper.to_entity(m) for m in result.scalars().all()]
