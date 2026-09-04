"""Login via bridge com a plataforma (ADR-0018). NUNCA logar senha/token."""

from datetime import datetime, timezone

from uuid6 import uuid7

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.user import User
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.support.utils.session_tokens import generate_session_token, hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import InvalidCredentialsError, RateLimitedError
from src.support.core.rate_limit import rate_limit
from src.support.core.settings import settings

# 10 tentativas por e-mail a cada 10 minutos. Mantido na v2: o limite da
# plataforma (100 req/min) é por IP, e no BFF todas as chamadas saem do nosso.
_SIGNIN_LIMIT = 10
_SIGNIN_WINDOW_MS = 600_000


class SignInAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()

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

        raw_token = generate_session_token()
        now = datetime.now(timezone.utc)
        await self.sessions.create(
            UserSession(
                uuid=uuid7(),
                token_hash=hash_session_token(raw_token),
                platform_access_token=data.access_token,
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
                user_username=user.username,
                last_platform_check_at=now,  # o signin acabou de validar
                created_at=now,
                updated_at=now,
            )
        )
        return SignInResult(
            user=user,
            session_token=raw_token,
            is_admin=user.email in settings.admin_emails,
        )
