"""I2 (ruling C7): `MENTOR_ENABLED` como kill switch de verdade também na rota
de prontidão — sem ele ligado, `LessonsController.status` nem chega a
consultar a aula."""

import pytest

from src.app.api.controllers.lessons_controller import LessonsController
from src.domain.lessons.actions.get_lesson_status_action import GetLessonStatusAction
from src.support.core.exceptions import NotFoundError


@pytest.mark.asyncio
async def test_mentor_disabled_is_404_before_looking_up_the_lesson(monkeypatch):
    import src.app.api.controllers.lessons_controller as lessons_ctrl

    monkeypatch.setattr(lessons_ctrl.settings, "MENTOR_ENABLED", False)

    async def _boom(self, platform_video_id):
        raise AssertionError("GetLessonStatusAction não deveria ser chamada com o mentor desligado")

    monkeypatch.setattr(GetLessonStatusAction, "execute", _boom)

    with pytest.raises(NotFoundError):
        await LessonsController.status("v1")


@pytest.mark.asyncio
async def test_mentor_enabled_still_calls_the_action(monkeypatch):
    import src.app.api.controllers.lessons_controller as lessons_ctrl

    monkeypatch.setattr(lessons_ctrl.settings, "MENTOR_ENABLED", True)

    async def _fake(self, platform_video_id):
        return {"status": "ready", "chunkCount": 3}

    monkeypatch.setattr(GetLessonStatusAction, "execute", _fake)

    result = await LessonsController.status("v1")

    assert result.status == "ready"
    assert result.chunk_count == 3
