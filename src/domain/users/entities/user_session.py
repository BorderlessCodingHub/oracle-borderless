from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class UserSession:
    """Sessão do oráculo (ADR-0018). Pura — sem SQLAlchemy.

    `token_hash` é o SHA-256 do token que vive no cookie `ob_session` (source
    `oracle_login`) ou do bearer opaco da plataforma repassado pelo proxy do
    Next.js (source `platform_bearer`); `platform_access_token` é o token
    opaco da Borderless — nunca sai do servidor.
    `user_*` é snapshot do login para `/auth/me` responder sem ir à rede;
    `user_membership/user_seniority/user_career_stage` é o snapshot do perfil
    usado no prompt de navegação sem ir à rede a cada turno.
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
    source: str = "oracle_login"  # "oracle_login" | "platform_bearer"
    user_membership: str | None = None
    user_seniority: str | None = None
    user_career_stage: str | None = None

    def seconds_since_platform_check(self, now: datetime) -> float:
        return (now - self.last_platform_check_at).total_seconds()
