from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidade resolvida da sessão (ADR-0018), injetada no request context
    pelo require_user. `name`/`username` vêm do snapshot da sessão — é o que
    `/auth/me` devolve sem ir à rede."""

    id: str
    email: str
    is_admin: bool = False
    name: str | None = None
    username: str | None = None
