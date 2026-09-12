from src.app.api.responses.lesson_status_response import LessonStatusResponse
from src.domain.lessons.actions.get_lesson_status_action import GetLessonStatusAction
from src.support.core.exceptions import NotFoundError
from src.support.core.settings import settings


class LessonsController:
    @staticmethod
    async def status(platform_video_id: str) -> LessonStatusResponse:
        """GET /lessons/{platform_video_id}/status — prontidão da aula para o mentor.

        `platform_video_id` é o id da PLATFORM (path param), não o `uuid`
        interno da aula. Aula não encontrada não é 404 nesse sentido: volta 200
        com `status="unknown"` — a aba distingue "ainda não indexada" de erro.

        I2 (ruling C7): com o mentor desligado (`MENTOR_ENABLED=false`) a rota
        nem chega a consultar a aula — 404 direto, mesmo kill switch de
        `ConversationController.ask`.
        """
        if not settings.MENTOR_ENABLED:
            raise NotFoundError("mentor desabilitado")
        result = await GetLessonStatusAction().execute(platform_video_id)
        return LessonStatusResponse.from_action_result(result)
