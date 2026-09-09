"""Cliente da API de navegação da borderless-api (spec §4). HTTP puro — roda na
fase de streaming sem sessão de banco (ADR-0020). O token do usuário viaja
SÓ no header; nunca é logado."""

import json
import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import DomainError, ExternalServiceUnavailableError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_PUBLIC_TARGET_KEYS = ("id", "path", "labelKey", "label")
_PUBLIC_SIGNAL_KEYS = ("matchedTags", "inProgress", "difficulty", "fallback")


class NavigationValidationError(DomainError):
    def __init__(self, message: str, valid_destinations: list[str]) -> None:
        super().__init__(message)
        self.valid_destinations = valid_destinations


class NavigationUnauthorizedError(DomainError):
    """Token da plataforma recusado pela API de navegação."""


def _pick(d: dict, keys: tuple[str, ...]) -> dict:
    return {k: d[k] for k in keys if k in d and d[k] is not None}


@dataclass(frozen=True)
class NavigationResult:
    destination: dict
    access: str
    unlock: dict | None
    signals: dict
    alternatives: list[dict]

    def to_public(self) -> dict:
        """Projeção que atravessa o redator (regra 4): sem `profile`, sem extras."""
        return {
            "destination": _pick(self.destination, _PUBLIC_TARGET_KEYS),
            "access": self.access,
            "unlock": dict(self.unlock) if self.unlock else None,
            "signals": _pick(self.signals, _PUBLIC_SIGNAL_KEYS),
            "alternatives": [_pick(a, _PUBLIC_TARGET_KEYS) for a in self.alternatives],
        }

    def to_tool_text(self) -> str:
        """O que o modelo lê: inclui `signals.profile` para frasear a resposta."""
        return json.dumps(
            {"destination": self.destination, "access": self.access, "unlock": self.unlock,
             "signals": self.signals, "alternatives": self.alternatives},
            ensure_ascii=False,
        )


class BorderlessNavigationClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}{path}"

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=settings.NAVIGATION_TIMEOUT_SECONDS)

    async def resolve(self, access_token: str, destination: str, topic: str | None = None, goal: str | None = None) -> NavigationResult:
        body: dict = {"destination": destination}
        if topic:
            body["topic"] = topic
        if goal:
            body["goal"] = goal
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/navigation/resolve"), json=body,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("navigation/resolve falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 400:
            error = _error_of(response)
            valid = error.get("details", {}).get("validDestinations") or []
            raise NavigationValidationError(error.get("message") or "destino inválido", [str(v) for v in valid])
        if response.status_code in (401, 403):
            raise NavigationUnauthorizedError("token recusado pela API de navegação")
        if response.status_code != 200:
            logger.warning("navigation/resolve devolveu %s", response.status_code)
            raise ExternalServiceUnavailableError("plataforma indisponível")
        try:
            data = response.json()["data"]
            return NavigationResult(
                destination=dict(data["destination"]), access=str(data["access"]),
                unlock=dict(data["unlock"]) if data.get("unlock") else None,
                signals=dict(data.get("signals") or {}), alternatives=list(data.get("alternatives") or []),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("navigation/resolve 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    async def catalog(self, access_token: str) -> list[dict]:
        try:
            async with self._http() as client:
                response = await client.get(self._url("/api/navigation/catalog"), headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc
        if response.status_code != 200:
            raise ExternalServiceUnavailableError(f"catalog devolveu {response.status_code}")
        try:
            return [dict(e) for e in response.json()["data"]["destinations"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceUnavailableError("catalog fora do contrato") from exc


def _error_of(response: httpx.Response) -> dict:
    try:
        return dict(response.json().get("error") or {})
    except ValueError:
        return {}
