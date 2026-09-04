"""Auth (ADR-0018). `POST /auth/login` é público (bridge com a plataforma);
`/auth/me` e `/auth/logout` ficam no `router` — o autodiscovery amarra
`require_user` mecanicamente."""

from fastapi import APIRouter

from src.app.api.controllers.auth_controller import AuthController

public_router = APIRouter(prefix="/auth", tags=["Auth"])
public_router.post("/login")(AuthController.login)

router = APIRouter(prefix="/auth", tags=["Auth"])
router.get("/me")(AuthController.me)
router.post("/logout", status_code=204)(AuthController.logout)
