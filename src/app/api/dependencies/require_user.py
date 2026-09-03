"""Identidade por request: valida o JWT da plataforma LOCALMENTE (ADR-0017)."""

import jwt
from fastapi import HTTPException, Request

from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.core.context import CurrentRequestContext
from src.support.core.settings import settings

_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


async def require_user(request: Request) -> AuthenticatedUser:
    verify_key = settings.BORDERLESS_JWT_VERIFY_KEY
    if not verify_key:
        # Misconfig de servidor, não culpa do usuário — não confundir com 401.
        raise HTTPException(status_code=503, detail="unavailable")

    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="not-authenticated", headers=_WWW_AUTH)

    try:
        claims = jwt.decode(
            token.strip(), verify_key, algorithms=[settings.BORDERLESS_JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        # Inválido, expirado ou assinatura errada — mesmo 401 genérico.
        raise HTTPException(status_code=401, detail="not-authenticated", headers=_WWW_AUTH)

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        # §9 do spec: sem claim de e-mail não há ownership nem allowlist.
        raise HTTPException(status_code=401, detail="not-authenticated", headers=_WWW_AUTH)

    user = AuthenticatedUser(
        id=str(claims.get("sub") or ""),
        email=email,
        is_admin=email in settings.admin_emails,
    )
    CurrentRequestContext.set_user(user)
    return user
