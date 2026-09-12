"""Cliente do entitlement do mentor: pergunta à plataforma, COM O BEARER DO
ALUNO (não o segredo interno), se ele enxerga esta aula.

Rota real (verificada em borderless-api/src/routes/api/programs.routes.ts):
`GET /api/programs/{programSlug}/modules/{moduleSlug}/videos/{videoSlug}`,
autenticada por `fastify.maybeAuthenticate` — que, com um bearer presente no
header `Authorization`, resolve a sessão do usuário como `fastify.authenticate`
faria (a diferença é só tolerar ausência de sessão, não a forma de autenticar).
Payload 200: `{"data": {"video": {..., "access": {"hasAccess": bool, ...}}}}`
(borderless-platform/src/services/api/programs/types.ts — `VideoPageDataSchema`
→ `VideoDetailSchema.access` → `AccessDescriptorSchema.hasAccess`, em
borderless-platform/src/services/api/comments/types.ts).

Autenticação diferente da ingestão (`BorderlessLessonsClient`, segredo
compartilhado): por isso um cliente separado — o bearer do aluno viaja SÓ no
header `Authorization` e nunca é logado.
"""

import httpx

from src.support.core.settings import settings


class BorderlessLessonAccessClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` existe para os testes injetarem httpx.MockTransport.
        self._transport = transport

    def _url(self, program_slug: str, module_slug: str, video_slug: str) -> str:
        base = settings.BORDERLESS_AUTH_URL.rstrip("/")
        return f"{base}/api/programs/{program_slug}/modules/{module_slug}/videos/{video_slug}"

    async def has_access(
        self, bearer: str, program_slug: str, module_slug: str, video_slug: str
    ) -> bool:
        """`hasAccess` em `data.video.access.hasAccess`. 404 (aula/módulo/programa
        inexistente do ponto de vista da plataforma) nega sem levantar; qualquer
        outro erro sobe — quem chama (CheckLessonAccessAction) fecha fail-closed."""
        async with httpx.AsyncClient(
            transport=self._transport, timeout=settings.NAVIGATION_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(
                self._url(program_slug, module_slug, video_slug),
                headers={"Authorization": f"Bearer {bearer}"},
            )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        video = response.json().get("data", {}).get("video", {})
        return bool(video.get("access", {}).get("hasAccess"))
