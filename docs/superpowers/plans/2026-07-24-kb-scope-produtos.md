# KB Scope → folder "Products" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restringir a base de conhecimento do oráculo à subárvore do folder "Products" do Notion, tornando qualquer outro folder (inclusive privados) estruturalmente não-consumível.

**Architecture:** Trocar a descoberta de páginas em `NotionClient.list_approved_pages()` de uma busca plana no workspace para uma travessia descendente a partir de uma página-raiz configurável (o folder "Products"). Tudo que é descoberto está por construção dentro de Products; o resto nunca é visitado. A `KnowledgeCurationPolicy` existente permanece como defesa-em-profundidade.

**Tech Stack:** FastAPI, Python 3.13, pydantic-settings, MCP (`@notionhq/notion-mcp-server`), pytest.

## Global Constraints

- Domain não importa infraestrutura (HTTP/FastAPI). `NotionClient` vive em `src/support/clients/` e pode usar MCP. *(CLAUDE.md regra 1)*
- Nada confidencial na KB: linhas de banco (`child_database`) nunca entram. *(CLAUDE.md regra 4)*
- Sem dependências novas. *(CLAUDE.md regra 10)*
- Root do folder Products (Notion): `23d8d655-c889-806d-8828-d527ce6a1529`.
- ADR obrigatório para decisão arquitetural, seguindo template em `docs/adr/README.md` (`## Status` + `## Resumo` de 3 blocos + `---` + corpo).

---

### Task 1: Setting `NOTION_KB_ROOT_PAGE_ID`

**Files:**
- Modify: `src/support/core/settings.py:42-44` (bloco "Base de conhecimento: Notion via MCP")
- Modify: `.env.example:23-25`
- Test: `tests/unit/support/core/test_settings_kb_root.py`

**Interfaces:**
- Produces: `settings.NOTION_KB_ROOT_PAGE_ID: str | None` (default `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/support/core/test_settings_kb_root.py`:

```python
from src.support.core.settings import Settings


def test_kb_root_page_id_defaults_to_none():
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_ID is None


def test_kb_root_page_id_reads_from_env(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_ID", "abc123")
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_ID == "abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/support/core/test_settings_kb_root.py -v`
Expected: FAIL — `AttributeError`/`assert` on missing `NOTION_KB_ROOT_PAGE_ID`.

- [ ] **Step 3: Add the setting**

In `src/support/core/settings.py`, replace the Notion block:

```python
    # --- Base de conhecimento: Notion via MCP ---
    NOTION_MCP_URL: str | None = None
    NOTION_MCP_TOKEN: str | None = None
```

with:

```python
    # --- Base de conhecimento: Notion via MCP ---
    NOTION_MCP_URL: str | None = None
    NOTION_MCP_TOKEN: str | None = None
    # Raiz da KB: a base é EXCLUSIVAMENTE o subtree deste folder do Notion
    # (folder "Products"). Sem ele, o sync aborta (ver NotionClient).
    NOTION_KB_ROOT_PAGE_ID: str | None = None
```

- [ ] **Step 4: Document in `.env.example`**

In `.env.example`, replace lines 23-25:

```
# --- Base de conhecimento: Notion via MCP (token JÁ disponível; preencher no final) ---
NOTION_MCP_URL=               # preencher
NOTION_MCP_TOKEN=             # preencher
```

with:

```
# --- Base de conhecimento: Notion via MCP (token JÁ disponível; preencher no final) ---
NOTION_MCP_URL=               # preencher
NOTION_MCP_TOKEN=             # preencher
# Raiz da KB: id da página "Products" do Notion. A KB é SÓ o subtree dela.
NOTION_KB_ROOT_PAGE_ID=23d8d655-c889-806d-8828-d527ce6a1529
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/support/core/test_settings_kb_root.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/support/core/settings.py .env.example tests/unit/support/core/test_settings_kb_root.py
git commit -m "feat(kb): add NOTION_KB_ROOT_PAGE_ID setting (folder Products)"
```

---

### Task 2: Travessia descendente em `NotionClient`

**Files:**
- Modify: `src/support/clients/notion/notion_client.py` (add import de `settings`; add `KnowledgeBaseConfigError`; add `_child_blocks`, `_collect_scope`; rewrite `list_approved_pages`; remove `_search_all`)
- Test: `tests/unit/support/clients/notion/test_notion_client_scope.py`

**Interfaces:**
- Consumes: `settings.NOTION_KB_ROOT_PAGE_ID` (Task 1); `KnowledgeCurationPolicy.should_ingest(NotionPageRef)`; `NotionPage` dataclass; `_parse_ts`.
- Produces:
  - `class KnowledgeBaseConfigError(RuntimeError)`
  - `NotionClient._collect_scope(self, call: ToolCall, root_id: str) -> list[NotionPage]`
  - `NotionClient._child_blocks(call: ToolCall, block_id: str) -> list[dict[str, Any]]`
  - `NotionClient.list_approved_pages(self) -> list[NotionPage]` (agora escopada ao root; **raise** `KnowledgeBaseConfigError` se root ausente).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/support/clients/notion/test_notion_client_scope.py`:

```python
import pytest

from src.support.clients.notion.notion_client import (
    KnowledgeBaseConfigError,
    NotionClient,
)
from src.support.core.settings import settings


def _child_page(bid: str, title: str) -> dict:
    return {
        "object": "block",
        "id": bid,
        "type": "child_page",
        "child_page": {"title": title},
        "last_edited_time": "2026-07-01T00:00:00.000Z",
    }


def _child_database(bid: str) -> dict:
    return {
        "object": "block",
        "id": bid,
        "type": "child_database",
        "child_database": {"title": "Onboarding Control"},
    }


def _paragraph(bid: str) -> dict:
    return {"object": "block", "id": bid, "type": "paragraph", "paragraph": {"rich_text": []}}


def _make_call(tree: dict[str, list[dict]], requested: list[str]):
    async def call(tool: str, args: dict):
        assert tool == "API-get-block-children"
        block_id = args["block_id"]
        requested.append(block_id)
        return {"results": tree.get(block_id, []), "has_more": False}

    return call


@pytest.mark.asyncio
async def test_collect_scope_returns_only_descendant_pages():
    # root → [A (ok), Backlog (denylist), DB (banco)] ; A → [A1 (ok)]
    tree = {
        "root": [_child_page("A", "Programs"), _child_page("BL", "Backlog Platform"), _child_database("DB")],
        "A": [_child_page("A1", "Bootcamp 2026"), _paragraph("p1")],
        "A1": [],
        "BL": [_child_page("BLX", "linha de backlog")],  # não deve ser visitado
    }
    requested: list[str] = []
    client = NotionClient()

    pages = await client._collect_scope(_make_call(tree, requested), "root")

    ids = {p.id for p in pages}
    assert ids == {"A", "A1"}                    # Backlog (denylist) e DB (banco) fora
    assert all(p.is_approved for p in pages)
    assert "BL" not in requested                 # subárvore de página rejeitada não é descida
    assert "DB" not in requested                 # child_database nunca é descido


@pytest.mark.asyncio
async def test_list_approved_pages_raises_when_root_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)
    client = NotionClient()

    with pytest.raises(KnowledgeBaseConfigError):
        await client.list_approved_pages()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'KnowledgeBaseConfigError'` / `AttributeError: _collect_scope`.

- [ ] **Step 3: Add import + error class**

In `src/support/clients/notion/notion_client.py`, after the existing imports (below the `page_markdown_assembler` import), add:

```python
from src.support.core.settings import settings
```

And after the imports, before `@dataclass class NotionPage`, add:

```python
class KnowledgeBaseConfigError(RuntimeError):
    """Configuração da base de conhecimento ausente/inválida (ex.: root não definido)."""
```

- [ ] **Step 4: Add traversal helpers**

In `class NotionClient`, add these two methods (near the other private MCP helpers):

```python
    async def _collect_scope(self, call: ToolCall, root_id: str) -> list[NotionPage]:
        """Percorre a subárvore de `root_id` e devolve só páginas-documento aprovadas.

        Desce apenas em `child_page` aprovadas pela policy. `child_database`
        (linhas de banco / PII) e demais blocos de conteúdo ficam fora — e a
        subárvore de uma página rejeitada pela denylist não é visitada.
        """
        approved: list[NotionPage] = []
        stack = [root_id]
        while stack:
            parent_id = stack.pop()
            for block in await self._child_blocks(call, parent_id):
                if block.get("type") != "child_page":
                    continue
                title = block.get("child_page", {}).get("title", "")
                ref = NotionPageRef(object_type="page", parent_type="page_id", title=title)
                if not self._policy.should_ingest(ref):
                    continue
                approved.append(
                    NotionPage(
                        id=block["id"],
                        title=title,
                        content="",
                        url="",
                        is_approved=True,
                        last_edited_time=_parse_ts(block.get("last_edited_time")),
                    )
                )
                stack.append(block["id"])
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
```

- [ ] **Step 5: Rewrite `list_approved_pages` and remove `_search_all`**

Replace the whole current `list_approved_pages` method:

```python
    async def list_approved_pages(self) -> list[NotionPage]:
        """Lista (metadados) as páginas-documento aprovadas pela curadoria."""
        async with notion_mcp_session() as call:
            raw = await self._search_all(call)

        approved: list[NotionPage] = []
        for item in raw:
            if item.get("object") != "page":
                continue
            title = _extract_title(item)
            ref = NotionPageRef(
                object_type="page",
                parent_type=item.get("parent", {}).get("type", ""),
                title=title,
            )
            if self._policy.should_ingest(ref):
                approved.append(
                    NotionPage(
                        id=item["id"],
                        title=title,
                        content="",
                        url=item.get("url", ""),
                        is_approved=True,
                        last_edited_time=_parse_ts(item.get("last_edited_time")),
                    )
                )
        return approved
```

with:

```python
    async def list_approved_pages(self) -> list[NotionPage]:
        """Páginas-documento aprovadas — só o subtree do folder raiz configurado.

        A KB é EXCLUSIVAMENTE a subárvore de `NOTION_KB_ROOT_PAGE_ID` (folder
        "Products"). Sem root configurado, **aborta** em vez de devolver ``[]``:
        o sync completo removeria (soft-delete) toda a base ao reconciliar.
        """
        root_id = settings.NOTION_KB_ROOT_PAGE_ID
        if not root_id or root_id.lstrip().startswith("#"):
            raise KnowledgeBaseConfigError(
                "NOTION_KB_ROOT_PAGE_ID não configurado — a KB é o subtree do folder "
                "Products; sem root, o sync abortaria e apagaria toda a base."
            )
        async with notion_mcp_session() as call:
            return await self._collect_scope(call, root_id)
```

Then delete the now-unused `_search_all` static method entirely:

```python
    @staticmethod
    async def _search_all(call: ToolCall) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {"query": "", "page_size": 100}
            if cursor:
                args["start_cursor"] = cursor
            data = await call("API-post-search", args)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                return results
            cursor = data.get("next_cursor")
```

Leave `_extract_title` in place (still used by `get_page`).

- [ ] **Step 6: Run the new tests**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the full documents + notion suite for regressions**

Run: `pytest tests/unit/domain/documents tests/unit/support/clients/notion -v`
Expected: PASS (policy tests, sync-action tests, new scope tests all green).

- [ ] **Step 8: Commit**

```bash
git add src/support/clients/notion/notion_client.py tests/unit/support/clients/notion/test_notion_client_scope.py
git commit -m "feat(kb): escopar list_approved_pages ao subtree do folder Products

Descoberta passa de busca plana no workspace para travessia descendente a
partir de NOTION_KB_ROOT_PAGE_ID. Folders fora de Products nunca são
visitados. Aborta (KnowledgeBaseConfigError) se o root não estiver setado,
evitando que o sync completo apague a base."
```

---

### Task 3: ADR-0011 — KB restrita a um root configurável

**Files:**
- Create: `docs/adr/0011-kb-restrita-root-notion.md`
- Modify: `docs/adr/README.md:28-29` (adicionar linha no índice)

**Interfaces:** documentação apenas. Sem código.

- [ ] **Step 1: Create the ADR**

Create `docs/adr/0011-kb-restrita-root-notion.md`:

```markdown
# ADR-0011 — Base de conhecimento restrita ao subtree de um root configurável do Notion

## Status

Aceito — 2026-07-24.

## Resumo

- **Decisão:** a KB do oráculo é EXCLUSIVAMENTE a subárvore de uma página-raiz
  configurável do Notion (`NOTION_KB_ROOT_PAGE_ID`, hoje o folder "Products");
  a descoberta de páginas é uma travessia descendente a partir desse root.
- **Aplica-se quando:** mexer em ingestão/sync da KB, curadoria, ou no escopo do
  que o oráculo pode responder.
- **Regra prática:** nada fora do subtree do root é descoberto, ingerido ou
  respondido. Sem root configurado, o sync **aborta** (não devolve lista vazia).

---

## Contexto

A regra inegociável nº 4 (nada confidencial) era aplicada por curadoria
**estrutural + denylist**: `KnowledgeCurationPolicy` deixava passar qualquer
página-documento (`parent = page/workspace`) e barrava linhas de banco. A
descoberta era uma busca plana no workspace inteiro (`API-post-search`), então
"aprovado" significava, na prática, *qualquer documento em qualquer folder* —
inclusive folders que a dona do produto não quer expor.

Uma busca plana só conhece o parent imediato de cada página, não sua
ancestralidade, então não consegue expressar "somente o folder Products".

## Decisão

Restringir a KB à subárvore de um único root configurável e trocar a descoberta
por uma travessia descendente (`API-get-block-children`) a partir dele. Blocos
`child_page` aprovados pela policy são coletados e recursados; `child_database`
e a subárvore de páginas rejeitadas não são visitados. `KnowledgeCurationPolicy`
permanece como defesa-em-profundidade. O root vem de `NOTION_KB_ROOT_PAGE_ID`;
sua ausência faz `list_approved_pages` lançar `KnowledgeBaseConfigError`, pois um
run completo de sync com lista vazia soft-deletaria toda a base.

## Consequências

- Garantia **estrutural**: folders fora do root nunca são lidos — mais forte que
  filtrar no fim.
- Re-apontar o escopo é trocar uma env var, sem deploy de código.
- Mais chamadas MCP (travessia) que a busca plana — aceitável para um job de sync.
- Páginas aninhadas dentro de blocos de layout (colunas/toggles) não são
  descidas (só `child_page`); revisitar se o folder passar a usar esse padrão.

## Alternativas consideradas

- **Busca plana + filtro por ancestralidade:** N chamadas extras por página e a
  busca ainda lê todos os folders no caminho. Descartada.
- **Allowlist de parents imediatos:** perde docs aninhados 2+ níveis. Descartada.
```

- [ ] **Step 2: Add the ADR to the index**

In `docs/adr/README.md`, after the ADR-0010 row (line 28), add:

```markdown
| [0011](0011-kb-restrita-root-notion.md) | Base de conhecimento restrita ao subtree de um root configurável do Notion | Aceito |
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0011-kb-restrita-root-notion.md docs/adr/README.md
git commit -m "docs(adr): ADR-0011 KB restrita ao subtree de um root configurável do Notion"
```

---

## Notas pós-implementação (fora dos commits de código)

- Atualizar as memórias `knowledge-curation-policy` e `notion-kb-structure`: a
  fronteira de curadoria agora é **root subtree (Products)**, com a policy como
  defesa-em-profundidade; `list_approved_pages` faz travessia, não busca plana.
- Confirmar que `.env` (não versionado) recebeu `NOTION_KB_ROOT_PAGE_ID`.
