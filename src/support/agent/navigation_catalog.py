"""Catálogo de destinos que o modelo lê na descrição da tool navigate_platform.

A API exige token de usuário, então o catálogo é buscado com o token do turno
corrente e cacheado por processo (NAVIGATION_CATALOG_TTL_S). Sem token ou com a
API fora, vale o snapshot embutido — a API continua sendo a fonte da verdade:
um id fora do catálogo dela volta como 400 com `validDestinations`.

A FALHA também é cacheada (R13, `NAVIGATION_CATALOG_RETRY_S`): sem isso, com a
API fora, cada turno seguinte repagava a chamada — e o timeout dela — no
caminho crítico. Durante o retry o snapshot é servido do cache; passado o
prazo, a API é tentada de novo."""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.support.clients.borderless.borderless_navigation_client import BorderlessNavigationClient
from src.support.core.settings import settings

logger = logging.getLogger(__name__)
_SNAPSHOT = Path(__file__).with_name("navigation_catalog_snapshot.json")


@dataclass
class _CachedCatalog:
    at: float
    entries: list[dict]
    negative: bool = False  # entries é o snapshot embutido: a API falhou

    def ttl(self) -> float:
        return settings.NAVIGATION_CATALOG_RETRY_S if self.negative else settings.NAVIGATION_CATALOG_TTL_S


def _format_entries(entries: list[dict]) -> str:
    """Formatador único: uma linha por destino `- <id> (<kind>): <description>`.
    Compartilhado por `describe()` (catálogo ao vivo) e `snapshot_text()`
    (fallback do snapshot embutido) — nenhum dos dois duplica o formato."""
    return "\n".join(f"- {e['id']} ({e['kind']}): {e['description']}" for e in entries)


class NavigationCatalog:
    _cache: _CachedCatalog | None = None  # por processo

    def __init__(self, client: BorderlessNavigationClient | None = None, clock: Callable[[], float] | None = None) -> None:
        self._client = client or BorderlessNavigationClient()
        self._clock = clock or time.monotonic

    @classmethod
    def reset(cls) -> None:
        cls._cache = None

    @staticmethod
    def snapshot() -> list[dict]:
        return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))

    @classmethod
    def snapshot_ids(cls) -> list[str]:
        return [e["id"] for e in cls.snapshot()]

    @classmethod
    def snapshot_text(cls) -> str:
        """Texto do snapshot embutido, no mesmo formato de `describe()` — usado
        como fallback por chamadores que não têm instância (ex.: docstring de tool)."""
        return _format_entries(cls.snapshot())

    async def entries(self, access_token: str | None) -> list[dict]:
        cache = type(self)._cache
        if cache is not None and self._clock() - cache.at < cache.ttl():
            return cache.entries
        if not access_token:
            # Turno sem token não pode nem tentar — e não envenena o cache do
            # processo com uma falha que nunca chegou a acontecer.
            return self.snapshot()
        try:
            entries = await self._client.catalog(access_token)
        except Exception:  # snapshot cobre; a API segue sendo a fonte da verdade
            logger.warning("catálogo de navegação indisponível; usando snapshot", exc_info=True)
            snapshot = self.snapshot()
            type(self)._cache = _CachedCatalog(at=self._clock(), entries=snapshot, negative=True)
            return snapshot
        type(self)._cache = _CachedCatalog(at=self._clock(), entries=entries)
        return entries

    async def ids(self, access_token: str | None) -> list[str]:
        return [e["id"] for e in await self.entries(access_token)]

    async def describe(self, access_token: str | None) -> str:
        return _format_entries(await self.entries(access_token))
