"""Login via bridge com a plataforma (ADR-0017). NUNCA logar senha/token."""

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.user import User
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import InvalidCredentialsError, RateLimitedError
from src.support.core.rate_limit import rate_limit
from src.support.core.settings import settings

_SIGNIN_LIMIT = 10
_SIGNIN_WINDOW_MS = 600_000  # 10 tentativas por e-mail a cada 10 minutos


class SignInAction:
    def __init__(self, auth_client: BorderlessAuthClient) -> None:
        self.auth_client = auth_client

    async def execute(self, email: str, password: str) -> SignInResult:
        email = email.strip().lower()
        if not email or not password:
            raise InvalidCredentialsError("credenciais vazias")

        if not await rate_limit(f"signin:{email}", _SIGNIN_LIMIT, _SIGNIN_WINDOW_MS):
            raise RateLimitedError("muitas tentativas de login")

        data = await self.auth_client.sign_in(email, password)
        user = User(
            id=data.user.id,
            email=data.user.email,
            name=data.user.name,
            username=data.user.username,
            career_stage=data.user.career_stage,
            email_verified=data.user.email_verified,
        )
        return SignInResult(
            user=user,
            access_token=data.access_token,
            expires_in=data.expires_in,
            is_admin=user.email in settings.admin_emails,
        )
