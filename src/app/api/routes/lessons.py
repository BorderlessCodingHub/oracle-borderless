"""Rota de prontidão de aula — exige usuário autenticado (ADR-0017): prontidão
de aula é informação de membro, não pública."""

from fastapi import APIRouter, Depends

from src.app.api.controllers.lessons_controller import LessonsController
from src.app.api.dependencies.require_user import require_user

router = APIRouter(
    prefix="/lessons", tags=["Lessons"], dependencies=[Depends(require_user)]
)
router.get("/{platform_video_id}/status")(LessonsController.status)
