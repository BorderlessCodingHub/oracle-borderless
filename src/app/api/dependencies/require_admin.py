"""Admin do /ops: allowlist ADMIN_EMAILS; quem não é admin recebe 404 (ADR-0017)."""

from fastapi import Depends

from src.app.api.dependencies.require_user import require_user
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.core.exceptions import NotFoundError


async def require_admin(
    user: AuthenticatedUser = Depends(require_user),
) -> AuthenticatedUser:
    if not user.is_admin:
        # 404, nunca 403: a página de ops não deve nem revelar que existe.
        raise NotFoundError("recurso não encontrado")
    return user
