"""Auth (ADR-0018).

`public_router`: `POST /auth/login` (bridge com a plataforma) e `POST /auth/logout`.
O logout é público DE PROPÓSITO: a `SignOutAction` já se autentica pelo hash do
cookie (só quem tem o cookie apaga a própria sessão) e precisa funcionar mesmo
quando o `require_user` não conseguiria — plataforma fora além do fail-open
(503) ou sessão já revogada (401). Se o logout ficasse atrás do guard, o cookie
sobreviveria e, com a plataforma de volta, o usuário reapareceria logado numa
máquina compartilhada.

`router`: `GET /auth/me` — o autodiscovery amarra `require_user` mecanicamente.
"""

from fastapi import APIRouter

from src.app.api.controllers.auth_controller import AuthController

public_router = APIRouter(prefix="/auth", tags=["Auth"])
public_router.post("/login")(AuthController.login)
public_router.post("/logout", status_code=204)(AuthController.logout)

router = APIRouter(prefix="/auth", tags=["Auth"])
router.get("/me")(AuthController.me)
