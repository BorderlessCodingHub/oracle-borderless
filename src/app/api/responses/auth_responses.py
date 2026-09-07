from pydantic import BaseModel

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.authenticated_user import AuthenticatedUser


class AuthUserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    username: str | None


class SessionResponse(BaseModel):
    """Shape único de `POST /auth/login` e `GET /auth/me`. NUNCA carrega token:
    a credencial vai no cookie httpOnly (ADR-0018)."""

    user: AuthUserResponse
    is_admin: bool

    @classmethod
    def from_result(cls, result: SignInResult) -> "SessionResponse":
        return cls(
            user=AuthUserResponse(
                id=result.user.id,
                email=result.user.email,
                name=result.user.name,
                username=result.user.username,
            ),
            is_admin=result.is_admin,
        )

    @classmethod
    def from_authenticated_user(cls, user: AuthenticatedUser) -> "SessionResponse":
        return cls(
            user=AuthUserResponse(id=user.id, email=user.email, name=user.name, username=user.username),
            is_admin=user.is_admin,
        )
