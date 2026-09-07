"""Logout (ADR-0018): invalida na plataforma (best-effort — descartar só
localmente deixaria a sessão viva lá) e apaga a nossa linha."""

from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.support.utils.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient


class SignOutAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()

    async def execute(self, raw_token: str) -> None:
        session = await self.sessions.get_by_token_hash(hash_session_token(raw_token))
        if session is None:
            return
        await self.auth_client.sign_out(session.platform_access_token)  # nunca lança
        await self.sessions.delete(session.uuid)
