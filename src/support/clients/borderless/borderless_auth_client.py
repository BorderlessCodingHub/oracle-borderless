"""Bridge de credenciais com a plataforma Borderless (ADR-0017; spec §3).

A key header é segredo de SERVIDOR. NUNCA logar senha nem accessToken — os
logs registram apenas status/tipo do erro.
"""

import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
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


class BorderlessAuthClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` existe para os testes injetarem httpx.MockTransport.
        self._transport = transport

    async def sign_in(self, email: str, password: str) -> PlatformSignIn:
        api_key = settings.BORDERLESS_AUTH_API_KEY
        if not api_key:
            raise ExternalServiceUnavailableError("BORDERLESS_AUTH_API_KEY ausente")

        url = f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}/api/auth/signin"
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    url,
                    json={"email": email, "password": password},
                    headers={settings.BORDERLESS_AUTH_KEY_HEADER: api_key},
                )
        except httpx.HTTPError as exc:
            logger.error("signin da plataforma falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 429:
            raise RateLimitedError("rate limit da plataforma")
        if response.status_code >= 500:
            logger.error("signin da plataforma devolveu %s", response.status_code)
            raise ExternalServiceUnavailableError("plataforma indisponível")
        if response.status_code != 200:
            raise InvalidCredentialsError("credenciais inválidas")

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
