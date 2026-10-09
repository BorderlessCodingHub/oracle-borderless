"""Página de ops — restrita a admins (allowlist ADMIN_EMAILS; ADR-0017)."""

from fastapi import APIRouter, Depends

from src.app.api.controllers.ops_controller import OpsController
from src.app.api.dependencies.require_admin import require_admin

router = APIRouter(prefix="/ops", tags=["Ops"], dependencies=[Depends(require_admin)])
router.get("/overview")(OpsController.overview)
router.get("/turns")(OpsController.turns)
router.get("/turns/{trace_id}")(OpsController.turn)
router.get("/eval")(OpsController.eval_report)
router.get("/mentor")(OpsController.mentor)
