from pydantic import BaseModel

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.user import User


class SignInUserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    username: str | None
    career_stage: str | None
    email_verified: bool | None

    @classmethod
    def from_entity(cls, user: User) -> "SignInUserResponse":
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            username=user.username,
            career_stage=user.career_stage,
            email_verified=user.email_verified,
        )


class SignInResponse(BaseModel):
    user: SignInUserResponse
    access_token: str
    expires_in: int | None
    is_admin: bool

    @classmethod
    def from_result(cls, result: SignInResult) -> "SignInResponse":
        return cls(
            user=SignInUserResponse.from_entity(result.user),
            access_token=result.access_token,
            expires_in=result.expires_in,
            is_admin=result.is_admin,
        )
