"""Entitlement do mentor: o aluno tem acesso a ESTA aula?

Fail-closed de propósito. A autenticação do Oracle tem fail-open de 10 min
(ADR-0017) porque lá o risco de errar é derrubar sessão válida; aqui o risco é
entregar conteúdo pago a quem não comprou, então indisponibilidade nega.
"""

import logging

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.core.exceptions import DomainError

logger = logging.getLogger(__name__)


class LessonAccessDeniedError(DomainError):
    """O aluno não tem acesso à aula — ou não deu para confirmar que tem."""


class CheckLessonAccessAction:
    def __init__(self, access_client, lesson_repo=None) -> None:
        self.access_client = access_client
        self.lessons = lesson_repo or LessonRepository()

    async def execute(self, bearer: str, platform_video_id: str) -> Lesson:
        lesson = await self.lessons.get_by_platform_video_id(platform_video_id)
        if lesson is None:
            raise LessonAccessDeniedError(f"aula {platform_video_id} não está indexada")

        try:
            allowed = await self.access_client.has_access(
                bearer, lesson.program_slug, lesson.module_slug, lesson.video_slug
            )
        except Exception as exc:
            logger.warning("entitlement indisponível para %s: %s", platform_video_id, exc)
            raise LessonAccessDeniedError("não foi possível confirmar o acesso à aula") from exc

        if not allowed:
            raise LessonAccessDeniedError("sem acesso a esta aula")
        return lesson
