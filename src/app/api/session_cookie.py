"""Cookie de sessão do oráculo (ADR-0018, spec §4.4).

HttpOnly (JS não lê), SameSite=Lax (bloqueia POST cross-site — é a proteção
CSRF; exige SPA e API no MESMO host), Secure fora de dev, Max-Age 7 dias
(mesma janela da plataforma; quem expira de verdade é ela).
"""

from fastapi import Response

from src.support.core.settings import settings

SESSION_COOKIE_NAME = "ob_session"
SESSION_COOKIE_MAX_AGE_S = 7 * 24 * 60 * 60


def _secure() -> bool:
    return settings.ENVIRONMENT != "development"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE_S,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=_secure()
    )
