from src.app.api.requests.sign_in_request import SignInRequest
from src.app.api.responses.auth_responses import SignInResponse
from src.domain.users.actions.sign_in_action import SignInAction
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient


class AuthController:
    @staticmethod
    async def login(data: SignInRequest) -> SignInResponse:
        action = SignInAction(auth_client=BorderlessAuthClient())
        result = await action.execute(data.email, data.password)
        return SignInResponse.from_result(result)
