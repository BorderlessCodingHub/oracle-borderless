from fastapi import Depends, Request, Response

from src.app.api.dependencies.require_user import require_user
from src.app.api.requests.sign_in_request import SignInRequest
from src.app.api.responses.auth_responses import SessionResponse
from src.app.api.session_cookie import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    set_session_cookie,
)
from src.domain.users.actions.sign_in_action import SignInAction
from src.domain.users.actions.sign_out_action import SignOutAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient


class AuthController:
    @staticmethod
    async def login(data: SignInRequest, response: Response) -> SessionResponse:
        action = SignInAction(auth_client=BorderlessAuthClient())
        result = await action.execute(data.email, data.password)
        set_session_cookie(response, result.session_token)
        return SessionResponse.from_result(result)

    @staticmethod
    async def me(user: AuthenticatedUser = Depends(require_user)) -> SessionResponse:
        # Só projeção do snapshot da sessão — sem Action (spec §4.3).
        return SessionResponse.from_authenticated_user(user)

    @staticmethod
    async def logout(request: Request) -> Response:
        raw_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
        if raw_token:
            await SignOutAction(auth_client=BorderlessAuthClient()).execute(raw_token)
        response = Response(status_code=204)
        clear_session_cookie(response)
        return response
