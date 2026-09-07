"""Identidade por request (ADR-0018): cookie `ob_session` → sessão → validação
na plataforma (cache 60s / fail-open 10min) → AuthenticatedUser no contexto.

O 401 é único e indistinguível (sem cookie, cookie desconhecido, sessão
revogada). Plataforma fora além do fail-open NÃO é 401: a
`ExternalServiceUnavailableError` sobe e o handler responde 503.
"""

from fastapi import HTTPException, Request

from src.app.api.session_cookie import clearing_cookie_headers, read_session_cookie
from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.context import CurrentRequestContext


async def require_user(request: Request) -> AuthenticatedUser:
    raw_token = read_session_cookie(request)
    if raw_token is None:
        raise HTTPException(status_code=401, detail="not-authenticated")

    user = await ResolveSessionAction(auth_client=BorderlessAuthClient()).execute(raw_token)
    if user is None:
        # Cookie presente mas sessão morta (desconhecida ou revogada): o mesmo
        # 401 genérico, só que apagando o cookie — senão o browser fica
        # replicando um token inútil até o próximo login.
        raise HTTPException(
            status_code=401, detail="not-authenticated", headers=clearing_cookie_headers()
        )

    CurrentRequestContext.set_user(user)
    return user
