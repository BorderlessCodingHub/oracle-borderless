"""Prontidão de uma aula para o mentor.

Existe para a aba Mentor não abrir o composer numa aula sem transcrição — o
pior momento possível de uma demonstração é o aluno perguntar e o mentor dizer
que não conhece a aula (spec §8).
"""

from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository


class GetLessonStatusAction:
    def __init__(self, lesson_repo=None, chunk_repo=None) -> None:
        self.lessons = lesson_repo or LessonRepository()
        self.chunks = chunk_repo or LessonChunkRepository()

    async def execute(self, platform_video_id: str) -> dict:
        """Estado de indexação da aula, pelo id da PLATFORM (não o `uuid` interno).

        `unknown` (aula não encontrada) NÃO é um erro: é o estado que diz à aba
        "ainda não indexada", distinto de um 4xx/5xx de falha real.
        """
        lesson = await self.lessons.get_by_platform_video_id(platform_video_id)
        if lesson is None:
            return {"status": "unknown", "chunkCount": 0}
        count = await self.chunks.count_for_lesson(lesson.uuid)
        return {"status": str(lesson.transcript_status), "chunkCount": count}
