"""Rota do oráculo — exige usuário autenticado (ADR-0017): sem login não há pergunta."""

from fastapi import APIRouter, Depends

from src.app.api.controllers.conversation_controller import ConversationController
from src.app.api.dependencies.require_user import require_user

router = APIRouter(
    prefix="/conversations", tags=["Conversations"], dependencies=[Depends(require_user)]
)
router.post("/ask")(ConversationController.ask)
router.get("")(ConversationController.list)
router.get("/{conversation_id}")(ConversationController.get)
