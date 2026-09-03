from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidade extraída do JWT, injetada no request context pelo require_user."""

    id: str
    email: str
    is_admin: bool = False
