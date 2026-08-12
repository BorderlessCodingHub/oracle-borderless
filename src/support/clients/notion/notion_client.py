"""Client da base de conhecimento — Notion via MCP (Model Context Protocol).

Fronteira com o Notion. **Só expõe conteúdo aprovado**: a curadoria
(`KnowledgeCurationPolicy`) barra linhas de banco (trackers/PII), deixando
passar só páginas-documento. Transporte via `@notionhq/notion-mcp-server`
(ADR-0010); truncagem de páginas grandes é contornada pelo
`PageMarkdownAssembler`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.domain.documents.services.knowledge_curation_policy import (
    KnowledgeCurationPolicy,
    NotionPageRef,
)
from src.support.clients.notion.mcp_session import ToolCall, notion_mcp_session
from src.support.clients.notion.page_markdown_assembler import PageMarkdownAssembler
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id


class KnowledgeBaseConfigError(RuntimeError):
    """Configuração da base de conhecimento ausente/inválida (ex.: root não definido)."""


@dataclass
class NotionPage:
    """Página do Notion trazida pelo MCP. Primitivos, não Entity de domínio."""

    id: str
    title: str
    content: str
    url: str
    is_approved: bool
    last_edited_time: datetime | None = None
    section: str | None = None  # ancestral de 1º nível abaixo do root (ADR-0012)
    kb_root_page_id: str | None = None  # root normalizado sob o qual foi achada


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in parts) or "(sem título)"
    return "(sem título)"


class NotionClient:
    """Fronteira com o Notion via MCP. Só páginas aprovadas."""

    def __init__(self) -> None:
        self._policy = KnowledgeCurationPolicy()

    async def get_page(self, page_id: str) -> NotionPage:
        """Página completa (metadados + markdown, sem truncagem)."""
        async with notion_mcp_session() as call:
            page = await call("API-retrieve-a-page", {"page_id": page_id})
            markdown = await self._assemble(call, page_id)

        title = _extract_title(page)
        parent_type = page.get("parent", {}).get("type", "")
        ref = NotionPageRef(object_type="page", parent_type=parent_type, title=title)
        return NotionPage(
            id=page_id,
            title=title,
            content=markdown,
            url=page.get("url", ""),
            is_approved=self._policy.should_ingest(ref),
            last_edited_time=_parse_ts(page.get("last_edited_time")),
        )

    async def get_page_markdown(self, page_id: str) -> str:
        """Markdown completo da página, contornando a truncagem do MCP."""
        async with notion_mcp_session() as call:
            return await self._assemble(call, page_id)

    async def get_page_in_scope(self, page_id: str) -> NotionPage | None:
        """Página **só se** dentro da subárvore de algum root; senão ``None``.

        Acesso avulso por id (ex.: tool do agente) não passa pela travessia de
        descoberta, então precisa checar ancestralidade — do contrário qualquer
        página do workspace visível à integração viraria contexto de resposta.
        """
        roots = self._require_roots()
        async with notion_mcp_session() as call:
            matched_root = await self._find_root(call, page_id, roots)
            if matched_root is None:
                return None
            page = await call("API-retrieve-a-page", {"page_id": page_id})
            markdown = await self._assemble(call, page_id)

        title = _extract_title(page)
        parent_type = page.get("parent", {}).get("type", "")
        ref = NotionPageRef(object_type="page", parent_type=parent_type, title=title)
        return NotionPage(
            id=page_id,
            title=title,
            content=markdown,
            url=page.get("url", ""),
            is_approved=self._policy.should_ingest(ref),
            last_edited_time=_parse_ts(page.get("last_edited_time")),
            kb_root_page_id=matched_root,
        )

    async def list_approved_pages(self) -> list[NotionPage]:
        """Páginas-documento aprovadas — a união dos subtrees dos roots configurados.

        A KB é EXCLUSIVAMENTE a união das subárvores de `NOTION_KB_ROOT_PAGE_IDS`.
        Sem nenhum root configurado, **aborta** em vez de devolver ``[]``: o sync
        completo removeria (soft-delete) toda a base ao reconciliar.

        Uma página alcançável a partir de dois roots fica registrada sob o
        primeiro root da ordem de declaração — `kb_root_page_id` é um valor só
        por documento, então a atribuição precisa ser determinística.
        """
        roots = self._require_roots()
        collected: list[NotionPage] = []
        seen: set[str | None] = set()
        async with notion_mcp_session() as call:
            for root_id in roots:
                for page in await self._collect_scope(call, root_id):
                    key = normalize_page_id(page.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(page)
        return collected

    @staticmethod
    def _require_roots() -> tuple[str, ...]:
        roots = settings.kb_root_page_ids
        if not roots:
            raise KnowledgeBaseConfigError(
                "NOTION_KB_ROOT_PAGE_IDS não configurado — a KB é a união dos "
                "subtrees dos roots liberados; sem root, o sync abortaria e "
                "apagaria toda a base."
            )
        return roots

    async def _find_root(
        self, call: ToolCall, page_id: str, roots: tuple[str, ...] | None = None
    ) -> str | None:
        """Qual root contém esta página? Sobe a cadeia de `parent`.

        Devolve o root normalizado que casou, ou ``None`` se a página não
        descende de nenhum. Para em `workspace` (topo) ou `database_id` (linha
        de banco): nenhum dos dois pode ser descendente de um root. `seen`
        protege de ciclo/repetição.

        Devolver o root — e não um booleano — é o que permite ao chamador
        gravar a procedência correta quando há vários roots possíveis.
        """
        targets = set(roots if roots is not None else self._require_roots())
        current = page_id
        seen: set[str | None] = set()
        while True:
            key = normalize_page_id(current)
            if key in targets:
                return key
            if key in seen:
                return None
            seen.add(key)
            page = await call("API-retrieve-a-page", {"page_id": current})
            parent = page.get("parent", {})
            if parent.get("type") != "page_id":
                return None  # workspace ou database_id — fora de toda subárvore
            current = parent["page_id"]

    async def _collect_scope(self, call: ToolCall, root_id: str) -> list[NotionPage]:
        """Percorre a subárvore de `root_id` e devolve só páginas-documento aprovadas.

        Desce apenas em `child_page` aprovadas pela policy. `child_database`
        (linhas de banco / PII) e demais blocos de conteúdo ficam fora — e a
        subárvore de uma página rejeitada pela denylist não é visitada.

        Cada página carrega sua `section`: o título do ancestral de primeiro nível
        abaixo do root. Filhos diretos do root são sua própria seção.
        """
        approved: list[NotionPage] = []
        stack: list[tuple[str, str | None]] = [(root_id, None)]
        while stack:
            parent_id, inherited = stack.pop()
            for block in await self._child_blocks(call, parent_id):
                if block.get("type") != "child_page":
                    continue
                title = block.get("child_page", {}).get("title", "")
                ref = NotionPageRef(object_type="page", parent_type="page_id", title=title)
                if not self._policy.should_ingest(ref):
                    continue
                section = inherited if inherited is not None else title.strip()
                approved.append(
                    NotionPage(
                        id=block["id"],
                        title=title,
                        content="",
                        url="",
                        is_approved=True,
                        last_edited_time=_parse_ts(block.get("last_edited_time")),
                        section=section,
                        kb_root_page_id=normalize_page_id(root_id),
                    )
                )
                stack.append((block["id"], section))
        return approved

    @staticmethod
    async def _child_blocks(call: ToolCall, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            data = await call("API-get-block-children", args)
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                return blocks
            cursor = data.get("next_cursor")

    # --- transporte MCP (privado) ---

    async def _assemble(self, call: ToolCall, page_id: str) -> str:
        assembler = PageMarkdownAssembler(
            lambda bid: self._fetch_markdown(call, bid),
            lambda bid: self._list_child_ids(call, bid),
        )
        return await assembler.assemble(page_id)

    @staticmethod
    async def _fetch_markdown(call: ToolCall, block_id: str) -> tuple[str, bool]:
        data = await call("API-retrieve-page-markdown", {"page_id": block_id})
        return data.get("markdown", ""), bool(data.get("truncated"))

    @staticmethod
    async def _list_child_ids(call: ToolCall, block_id: str) -> list[str]:
        ids: list[str] = []
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            data = await call("API-get-block-children", args)
            ids.extend(b["id"] for b in data.get("results", []))
            if not data.get("has_more"):
                return ids
            cursor = data.get("next_cursor")
