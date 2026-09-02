"""Client da base de conhecimento — Notion via MCP (Model Context Protocol).

Fronteira com o Notion. **Não filtra sozinho** — devolve o veredito da
curadoria (`KnowledgeCurationPolicy`) em `is_approved` e cabe ao **chamador**
aplicá-lo. Os dois caminhos têm garantias diferentes:

- `list_approved_pages` (travessia de descoberta) **já** filtra pela policy —
  só páginas-documento aprovadas voltam, e a subárvore de uma página rejeitada
  nem é visitada.
- `get_page`/`get_page_with_provenance` (leitura por id avulso) devolvem a
  página **completa** — título, url e markdown, inclusive de linha de banco —
  com `is_approved=False` quando reprovada. Quem chama por id precisa checar
  o veredito antes de usar o conteúdo: `FetchNotionTool`
  (`src/support/agent/tools.py`) e `KnowledgeIngestCommand`
  (`src/app/console/commands/knowledge_ingest_command.py`) já fazem isso.

Transporte via `@notionhq/notion-mcp-server` (ADR-0010); truncagem de páginas
grandes é contornada pelo `PageMarkdownAssembler`.
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
from src.support.utils.notion_ids import normalize_page_id


class KnowledgeBaseConfigError(RuntimeError):
    """Configuração/descoberta da base de conhecimento ausente/inválida (ex.:
    nenhuma página de nível de workspace visível, ou paginação do `search`
    malformada)."""


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


@dataclass
class WorkspaceRootPage:
    """Página no nível do workspace visível à integração. Id já normalizado."""

    id: str
    title: str


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
    """Fronteira com o Notion via MCP.

    Devolve o veredito de curadoria em `is_approved`; aplicá-lo é
    responsabilidade do chamador (ver docstring do módulo). A travessia de
    descoberta (`list_approved_pages`) é a exceção — ela já filtra.
    """

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

    async def get_page_with_provenance(self, page_id: str) -> NotionPage:
        """Página completa + a página de topo de onde ela descende.

        Não recusa por ancestralidade (ADR-0015): o escopo é a permissão da
        integração, que o próprio MCP aplica negando acesso. O veredito de
        ingestão/serviço vem de `is_approved` (`KnowledgeCurationPolicy`) e
        **precisa ser checado pelo chamador** — é o que barra linha de banco
        (PII) neste caminho.
        """
        async with notion_mcp_session() as call:
            provenance = await self._find_top_level_page(call, page_id)
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
            kb_root_page_id=provenance,
        )

    async def list_approved_pages(self) -> list[NotionPage]:
        """Páginas-documento aprovadas — a união dos subtrees dos roots descobertos.

        Os roots são as páginas de nível de workspace que a integração enxerga
        (ADR-0015): o que a dona do produto compartilha é o escopo, sem segunda
        lista para manter em sincronia.

        Descoberta vazia **aborta** em vez de devolver ``[]``: nenhum root
        visível significa token revogado ou MCP fora do ar, e a reconciliação
        do sync soft-deletaria a base inteira numa única rodada.

        Uma página alcançável a partir de dois roots fica registrada sob o
        primeiro descoberto — `kb_root_page_id` é um valor só por documento,
        então a atribuição precisa ser determinística.

        O próprio root passa pela `KnowledgeCurationPolicy` antes de ser
        percorrido — a denylist de títulos vale em todos os níveis, não só
        dentro da subárvore.
        """
        collected: list[NotionPage] = []
        seen: set[str | None] = set()
        async with notion_mcp_session() as call:
            roots = await self._workspace_root_pages(call)
            if not roots:
                raise KnowledgeBaseConfigError(
                    "a integração do Notion não enxerga nenhuma página de nível "
                    "de workspace — token revogado, MCP fora do ar, ou busca "
                    "vazia por erro. Sync abortado: reconciliar com descoberta "
                    "vazia apagaria toda a base."
                )
            for root in roots:
                # A denylist de títulos é defesa em profundidade em TODOS os
                # níveis (ver ADR-0015, "Por que topo + subárvore, e não busca
                # plana") — inclusive o próprio root. Sem esta checagem, uma
                # página de topo com título de tracker (ex.: "Sprints 2026")
                # nunca entraria ela mesma, mas cada filho seu entraria por
                # conta própria em `_collect_scope`, porque `_collect_scope`
                # só poda a partir dos blocos que visita — nunca do root que
                # recebe. Compartilhar a página com a integração bastaria
                # para ingerir a subárvore inteira.
                ref = NotionPageRef(object_type="page", parent_type="workspace", title=root.title)
                if not self._policy.should_ingest(ref):
                    continue
                for page in await self._collect_scope(call, root.id):
                    key = normalize_page_id(page.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(page)
        return collected

    async def list_workspace_root_pages(self) -> list[WorkspaceRootPage]:
        """Páginas de nível de workspace que a integração enxerga — o escopo da KB.

        É a superfície de permissão do lado do Notion: o que a dona do produto
        liberou é o que o oráculo lê (ADR-0015). Não aplica escopo nenhum por
        cima disso, de propósito.
        """
        async with notion_mcp_session() as call:
            return await self._workspace_root_pages(call)

    @staticmethod
    async def _workspace_root_pages(call: ToolCall) -> list[WorkspaceRootPage]:
        pages: list[WorkspaceRootPage] = []
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "page_size": 100,
            }
            if cursor:
                args["start_cursor"] = cursor
            data = await call("API-post-search", args)
            for page in data.get("results", []):
                if page.get("parent", {}).get("type") != "workspace":
                    continue
                page_id = normalize_page_id(page.get("id"))
                if page_id:
                    pages.append(WorkspaceRootPage(id=page_id, title=_extract_title(page)))
            if not data.get("has_more"):
                return pages  # fim normal de paginação
            if not data.get("next_cursor"):
                # `has_more=True` sem `next_cursor` não é fim de paginação —
                # é o `search` respondendo de forma malformada. Continuar o
                # laço penduraria (`cursor` voltaria a `None`, args idênticos
                # ao primeiro loop, `while True` nunca sairia, e o
                # SyncKnowledgeBaseJob seguraria o advisory lock para sempre).
                # Devolver a lista parcial em silêncio seria pior: o sync
                # rodaria normalmente e a reconciliação soft-deletaria todo
                # documento sob os roots que ficaram de fora — sem nada
                # ligando o sintoma à causa. Levanta alto, na mesma família de
                # "token revogado / MCP fora do ar".
                raise KnowledgeBaseConfigError(
                    "a paginação do `search` do Notion veio malformada "
                    "(has_more=True sem next_cursor) — o escopo descoberto "
                    "seria parcial. Sync abortado."
                )
            cursor = data.get("next_cursor")

    @staticmethod
    async def _find_top_level_page(call: ToolCall, page_id: str) -> str | None:
        """De qual página de topo esta página descende? Sobe a cadeia de `parent`.

        Devolve o id normalizado da página cujo pai é o `workspace` — a
        procedência que vai para `kb_root_page_id`. Devolve ``None`` quando a
        cadeia termina em `database_id`/`data_source_id` (linha de banco não
        descende de página de topo) ou entra em ciclo.

        Não autoriza nada (ADR-0015): quem decide se a página é ingerível é a
        `KnowledgeCurationPolicy`, via `is_approved`. Antes esta subida recusava
        por não achar um root da allowlist, e barrava linha de banco por efeito
        colateral — a recusa agora é explícita no chamador.
        """
        current = page_id
        seen: set[str | None] = set()
        while True:
            key = normalize_page_id(current)
            if key in seen:
                return None
            seen.add(key)
            page = await call("API-retrieve-a-page", {"page_id": current})
            parent = page.get("parent", {})
            if parent.get("type") == "workspace":
                return key
            if parent.get("type") != "page_id":
                return None  # linha de banco ou parent desconhecido
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
