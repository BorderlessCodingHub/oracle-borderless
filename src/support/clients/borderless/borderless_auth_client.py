"""Bridge com a plataforma Borderless (ADR-0018; spec §3).

O login é PÚBLICO (não existe key de app). O `accessToken` é sessão opaca do
Better Auth: validar = `GET /api/users/profile`. NUNCA logar senha nem token —
os logs registram apenas status/`error.type`.
"""

import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
    RateLimitedError,
)
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class PlatformUser:
    id: str
    email: str
    name: str | None
    username: str | None
    career_stage: str | None
    email_verified: bool | None


@dataclass(frozen=True)
class PlatformSignIn:
    user: PlatformUser
    access_token: str
    expires_in: int | None


@dataclass(frozen=True)
class PlatformProfile:
    """Resposta de `GET /api/users/profile` — o que interessa para autorização."""

    id: str
    email: str
    name: str | None
    username: str | None
    membership: str | None
    community_role: str | None


def _error_envelope(response: httpx.Response) -> tuple[str | None, str | None]:
    """(`error.type`, `error.message`) do envelope da plataforma; (None, None)
    quando o corpo não segue o contrato (proxy devolvendo HTML, etc.)."""
    try:
        error = response.json()["error"]
        type_ = error.get("type")
        message = error.get("message")
        return (str(type_) if type_ else None, str(message) if message else None)
    except (ValueError, KeyError, TypeError, AttributeError):
        return (None, None)


class BorderlessAuthClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` existe para os testes injetarem httpx.MockTransport.
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}{path}"

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=_TIMEOUT_SECONDS)

    # --- signin ---

    async def sign_in(self, email: str, password: str) -> PlatformSignIn:
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/auth/signin"), json={"email": email, "password": password}
                )
        except httpx.HTTPError as exc:
            logger.error("signin da plataforma falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 200:
            return self._parse_sign_in(response, email)
        raise self._sign_in_error(response)

    @staticmethod
    def _sign_in_error(response: httpx.Response) -> Exception:
        """Mapeia por `error.type` (campo estável); cai no status quando o
        envelope não vem. `FORBIDDEN` é o único caso que repassa a message."""
        error_type, message = _error_envelope(response)
        status = response.status_code

        if error_type == "FORBIDDEN" or (error_type is None and status == 403):
            return ForbiddenError(message or "acesso negado pela plataforma")
        if error_type in ("VALIDATION", "UNAUTHORIZED") or (
            error_type is None and status in (400, 401)
        ):
            return InvalidCredentialsError("credenciais inválidas")
        if error_type == "TOO_MANY_REQUESTS" or (error_type is None and status == 429):
            return RateLimitedError("rate limit da plataforma")

        logger.error("signin da plataforma devolveu %s (type=%s)", status, error_type)
        return ExternalServiceUnavailableError("plataforma indisponível")

    @staticmethod
    def _parse_sign_in(response: httpx.Response, email: str) -> PlatformSignIn:
        try:
            body = response.json()
            user = body["data"]["user"]
            token = body["data"]["token"]
            return PlatformSignIn(
                user=PlatformUser(
                    id=str(user.get("id", "")),
                    email=str(user.get("email") or email).strip().lower(),
                    name=user.get("name"),
                    username=user.get("username"),
                    career_stage=user.get("careerStage"),
                    email_verified=user.get("emailVerified"),
                ),
                access_token=str(token["accessToken"]),
                expires_in=token.get("expiresIn"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("signin 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    # --- profile (validação de sessão) ---

    async def get_profile(self, access_token: str) -> PlatformProfile | None:
        """200 → perfil (sessão válida). 401 → None (expirada/revogada). Qualquer
        outra coisa → ExternalServiceUnavailableError, para o fail-open decidir."""
        try:
            async with self._http() as client:
                response = await client.get(
                    self._url("/api/users/profile"),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("profile da plataforma falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 401:
            return None
        if response.status_code != 200:
            logger.warning("profile da plataforma devolveu %s", response.status_code)
            raise ExternalServiceUnavailableError("plataforma indisponível")

        try:
            user = response.json()["data"]["user"]
            return PlatformProfile(
                id=str(user["id"]),
                email=str(user.get("email") or "").strip().lower(),
                name=user.get("name"),
                username=user.get("username"),
                membership=user.get("membership"),
                community_role=user.get("communityRole"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("profile 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    # --- signout ---

    async def sign_out(self, access_token: str) -> None:
        """Best-effort: invalida a sessão na plataforma. Nunca lança — o logout
        local acontece de qualquer jeito; o log registra a falha."""
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/auth/signout"),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("signout da plataforma falhou na rede: %s", type(exc).__name__)
            return
        if response.status_code >= 400:
            logger.warning("signout da plataforma devolveu %s", response.status_code)
