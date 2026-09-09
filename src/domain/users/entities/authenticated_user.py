from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidade resolvida da sessão (ADR-0018), injetada no request context
    pelo require_user. `name`/`username` vêm do snapshot da sessão — é o que
    `/auth/me` devolve sem ir à rede. `membership`/`seniority`/`career_stage`
    vêm do mesmo snapshot e alimentam o prompt de navegação do oráculo.
    `session_source` diz por qual caminho a identidade veio (`"oracle_login"`
    do cookie, `"platform_bearer"` do proxy da Platform): é o que decide se o
    turno recebe a tool de navegação — só o cliente embutido na Platform sabe
    executar um redirect (R12/ADR-0022)."""

    id: str
    email: str
    is_admin: bool = False
    name: str | None = None
    username: str | None = None
    platform_access_token: str | None = None  # só no servidor; nunca em eventos/logs
    membership: str | None = None
    seniority: str | None = None
    career_stage: str | None = None
    session_source: str | None = None  # "oracle_login" | "platform_bearer"
