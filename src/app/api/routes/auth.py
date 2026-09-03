"""Login — rota pública deliberada (bridge com a plataforma; ADR-0017)."""

from fastapi import APIRouter

from src.app.api.controllers.auth_controller import AuthController

public_router = APIRouter(prefix="/auth", tags=["Auth"])
public_router.post("/login")(AuthController.login)
