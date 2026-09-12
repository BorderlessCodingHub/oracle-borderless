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
    """O aluno não tem acesso à aula — ou não deu para confirmar que tem.

    M1: a mensagem da exceção é o que vira corpo do 403 (`exception_handlers.py`)
    — precisa ser OPACA em todos os casos (aula desconhecida, entitlement
    indisponível, acesso negado de fato). Diferenciar os casos no corpo HTTP
    ensinaria um cliente malicioso a distinguir "aula não indexada" de "aula
    indexada mas eu não comprei" só tentando ids ao acaso; a distinção real
    (para debug) fica só no log do servidor, via `logger.warning` abaixo.
    """


_OPAQUE_MESSAGE = "sem acesso a esta aula"


class CheckLessonAccessAction:
    def __init__(self, access_client, lesson_repo=None) -> None:
        self.access_client = access_client
        self.lessons = lesson_repo or LessonRepository()

    async def execute(self, bearer: str, platform_video_id: str) -> Lesson:
        lesson = await self.lessons.get_by_platform_video_id(platform_video_id)
        if lesson is None:
            logger.warning("aula %s não está indexada — negando (mensagem opaca ao cliente)", platform_video_id)
            raise LessonAccessDeniedError(_OPAQUE_MESSAGE)

        try:
            allowed = await self.access_client.has_access(
                bearer, lesson.program_slug, lesson.module_slug, lesson.video_slug
            )
        except Exception as exc:
            logger.warning("entitlement indisponível para %s: %s — negando (mensagem opaca ao cliente)", platform_video_id, exc)
            raise LessonAccessDeniedError(_OPAQUE_MESSAGE) from exc

        if not allowed:
            logger.warning("acesso negado a %s pela plataforma — negando (mensagem opaca ao cliente)", platform_video_id)
            raise LessonAccessDeniedError(_OPAQUE_MESSAGE)
        return lesson
