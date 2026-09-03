"""Forja JWTs de teste. O conftest configura settings p/ HS256 + segredo fixo."""

import time

import jwt

TEST_JWT_SECRET = "segredo-de-teste"
TEST_JWT_ALGORITHM = "HS256"


def forge_token(
    email: str,
    *,
    sub: str = "user-1",
    expires_in: int = 3600,
    secret: str = TEST_JWT_SECRET,
    **claims,
) -> str:
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + expires_in}
    payload.update(claims)
    return jwt.encode(payload, secret, algorithm=TEST_JWT_ALGORITHM)


def auth_headers(email: str, **kw) -> dict[str, str]:
    return {"Authorization": f"Bearer {forge_token(email, **kw)}"}
