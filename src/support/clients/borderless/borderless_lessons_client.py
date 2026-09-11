"""Cliente das rotas /api/internal da borderless-api — catálogo de aulas e URL
de mídia para a ingestão do mentor (spec §6). Autenticado por segredo
compartilhado em header, não por sessão de usuário: o consumidor é um lote
offline. O segredo viaja SÓ no header e nunca é logado.

Duas observações do lado da API que NÃO viram lógica aqui, só documentação:
`contentType` do Panda Video é `application/vnd.apple.mpegurl` (manifesto
HLS — a etapa de áudio repassa a URL direto pro ffmpeg) e `durationSeconds`
hoje sempre vem `None`.
"""

import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import DomainError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_HEADER = "X-Internal-Secret"
_TIMEOUT_SECONDS = 30.0


class LessonCatalogUnavailableError(DomainError):
    """A borderless-api não respondeu o que a ingestão precisa."""


@dataclass(frozen=True)
class CatalogLesson:
    platform_video_id: str
    program_slug: str
    module_slug: str
    video_slug: str
    title: str
    provider: str
    provider_ref: str
    duration_seconds: int | None


@dataclass(frozen=True)
class LessonMedia:
    url: str
    expires_at: str | None
    content_type: str | None


class BorderlessLessonsClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` existe para os testes injetarem httpx.MockTransport.
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}{path}"

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=_TIMEOUT_SECONDS)

    async def _get(self, path: str) -> dict:
        if not settings.BORDERLESS_INTERNAL_SECRET or not settings.BORDERLESS_INTERNAL_SECRET.strip():
            # Falha cedo em vez de mandar o header vazio: uma borderless-api
            # que exige o segredo devolveria 401/403 de qualquer forma, mas
            # aqui a causa fica clara sem depender do comportamento do lado
            # de lá.
            raise LessonCatalogUnavailableError("BORDERLESS_INTERNAL_SECRET não configurado")
        try:
            async with self._http() as client:
                response = await client.get(
                    self._url(path), headers={_HEADER: settings.BORDERLESS_INTERNAL_SECRET}
                )
        except httpx.HTTPError as exc:
            logger.warning("%s falhou na rede: %s", path, type(exc).__name__)
            raise LessonCatalogUnavailableError(
                f"falha ao chamar {path}: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            logger.warning("%s devolveu %s", path, response.status_code)
            raise LessonCatalogUnavailableError(f"{path} respondeu {response.status_code}")
        try:
            return dict(response.json()["data"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("%s 200 fora do contrato: %s", path, type(exc).__name__)
            raise LessonCatalogUnavailableError(f"{path} fora do contrato") from exc

    async def list_program_lessons(self, program_slug: str) -> list[CatalogLesson]:
        path = f"/api/internal/programs/{program_slug}/lessons"
        data = await self._get(path)
        try:
            return [
                CatalogLesson(
                    platform_video_id=row["id"],
                    program_slug=row["programSlug"],
                    module_slug=row["moduleSlug"],
                    video_slug=row["videoSlug"],
                    title=row["title"],
                    provider=row["provider"],
                    provider_ref=row["providerRef"],
                    duration_seconds=row.get("durationSeconds"),
                )
                for row in data.get("lessons", [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("%s 200 fora do contrato: %s", path, type(exc).__name__)
            raise LessonCatalogUnavailableError(f"{path} fora do contrato") from exc

    async def get_media(self, video_id: str) -> LessonMedia:
        path = f"/api/internal/videos/{video_id}/media"
        data = await self._get(path)
        try:
            return LessonMedia(
                url=data["url"],
                expires_at=data.get("expiresAt"),
                content_type=data.get("contentType"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("%s 200 fora do contrato: %s", path, type(exc).__name__)
            raise LessonCatalogUnavailableError(f"{path} fora do contrato") from exc
