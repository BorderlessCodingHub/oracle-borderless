"""Reconcilia o catálogo de aulas da plataforma com a tabela `lessons`.

Só escreve campos de catálogo: o `upsert_from_catalog` do repositório preserva
estado de transcrição de propósito, para que re-sincronizar não jogue fora
trabalho já feito.
"""

from uuid6 import uuid7

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_repository import LessonRepository


class SyncProgramLessonsAction:
    def __init__(self, lessons_client, lesson_repo=None) -> None:
        self.lessons_client = lessons_client
        self.lessons = lesson_repo or LessonRepository()

    async def execute(self, program_slug: str) -> list[Lesson]:
        rows = await self.lessons_client.list_program_lessons(program_slug)
        result: list[Lesson] = []
        for row in rows:
            result.append(
                await self.lessons.upsert_from_catalog(
                    Lesson(
                        uuid=uuid7(),
                        platform_video_id=row.platform_video_id,
                        program_slug=row.program_slug,
                        module_slug=row.module_slug,
                        video_slug=row.video_slug,
                        title=row.title,
                        duration_seconds=row.duration_seconds,
                        provider=row.provider,
                        provider_ref=row.provider_ref,
                        transcript_status=TranscriptStatus.PENDING,
                    )
                )
            )
        return result
