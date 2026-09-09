from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidade resolvida da sessão (ADR-0018), injetada no request context
    pelo require_user. `name`/`username` vêm do snapshot da sessão — é o que
    `/auth/me` devolve sem ir à rede. `membership`/`seniority`/`career_stage`
    vêm do mesmo snapshot e alimentam o prompt de navegação do oráculo."""

    id: str
    email: str
    is_admin: bool = False
    name: str | None = None
    username: str | None = None
    platform_access_token: str | None = None  # só no servidor; nunca em eventos/logs
    membership: str | None = None
    seniority: str | None = None
    career_stage: str | None = None
