from src.app.api.responses.lesson_status_response import LessonStatusResponse
from src.domain.lessons.actions.get_lesson_status_action import GetLessonStatusAction


class LessonsController:
    @staticmethod
    async def status(platform_video_id: str) -> LessonStatusResponse:
        """GET /lessons/{platform_video_id}/status — prontidão da aula para o mentor.

        `platform_video_id` é o id da PLATFORM (path param), não o `uuid`
        interno da aula. Aula não encontrada não é 404: volta 200 com
        `status="unknown"` — a aba distingue "ainda não indexada" de erro.
        """
        result = await GetLessonStatusAction().execute(platform_video_id)
        return LessonStatusResponse.from_action_result(result)
