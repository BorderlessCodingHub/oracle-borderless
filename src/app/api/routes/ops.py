"""Página de ops — hoje aberta; `require_admin` é o encaixe único da auth de admin."""

from fastapi import APIRouter, Depends

from src.app.api.controllers.ops_controller import OpsController
from src.app.api.dependencies.require_admin import require_admin

public_router = APIRouter(
    prefix="/ops", tags=["Ops"], dependencies=[Depends(require_admin)]
)
public_router.get("/overview")(OpsController.overview)
public_router.get("/turns")(OpsController.turns)
public_router.get("/turns/{trace_id}")(OpsController.turn)
public_router.get("/eval")(OpsController.eval_report)
