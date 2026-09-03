from dataclasses import dataclass

from src.domain.users.entities.user import User


@dataclass(frozen=True)
class SignInResult:
    user: User
    access_token: str
    expires_in: int | None
    is_admin: bool
