from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class UserSession:
    """Sessão do oráculo (ADR-0018). Pura — sem SQLAlchemy.

    `token_hash` é o SHA-256 do token que vive no cookie `ob_session`;
    `platform_access_token` é o token opaco da Borderless — nunca sai do servidor.
    `user_*` é snapshot do login para `/auth/me` responder sem ir à rede.
    `last_platform_check_at` é o cache da validação contra a plataforma.
    """

    uuid: UUID
    token_hash: str
    platform_access_token: str
    user_id: str
    user_email: str
    user_name: str | None
    user_username: str | None
    last_platform_check_at: datetime
    created_at: datetime
    updated_at: datetime

    def seconds_since_platform_check(self, now: datetime) -> float:
        return (now - self.last_platform_check_at).total_seconds()
