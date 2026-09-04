"""Identidade por request (ADR-0018): cookie `ob_session` → sessão → validação
na plataforma (cache 60s / fail-open 10min) → AuthenticatedUser no contexto.

O 401 é único e indistinguível (sem cookie, cookie desconhecido, sessão
revogada). Plataforma fora além do fail-open NÃO é 401: a
`ExternalServiceUnavailableError` sobe e o handler responde 503.
"""

from fastapi import HTTPException, Request

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.context import CurrentRequestContext


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="not-authenticated")


async def require_user(request: Request) -> AuthenticatedUser:
    raw_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not raw_token:
        raise _unauthorized()

    user = await ResolveSessionAction(auth_client=BorderlessAuthClient()).execute(raw_token)
    if user is None:
        raise _unauthorized()

    CurrentRequestContext.set_user(user)
    return user
