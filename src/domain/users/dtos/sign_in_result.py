from dataclasses import dataclass

from src.domain.users.entities.user import User


@dataclass(frozen=True)
class SignInResult:
    user: User
    # Token de sessão do oráculo, CRU: só atravessa até o Set-Cookie. Nunca
    # logar nem persistir (o banco guarda o hash).
    session_token: str
    is_admin: bool
