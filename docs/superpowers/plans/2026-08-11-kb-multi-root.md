# Escopo multi-root da KB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalizar o escopo da base de conhecimento de um único root do Notion para uma lista de roots irmãos, preservando as garantias de fail-closed e de escopo-como-invariante-de-leitura.

**Architecture:** `NOTION_KB_ROOT_PAGE_ID` (singular) vira `NOTION_KB_ROOT_PAGE_IDS` (CSV), lido por uma property `Settings.kb_root_page_ids` que devolve ids normalizados e deduplicados. A descoberta percorre cada root e **etiqueta cada página com o root sob o qual foi encontrada**; a recuperação troca `== root` por `IN (roots)`; o acesso avulso por id aceita a página quando algum ancestral pertence à lista. Um `DetectKbRootDriftAction` compara a allowlist com o que a integração enxerga no workspace.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, pytest + pytest-asyncio, Notion via MCP.

## Global Constraints

- Fase 1a da spec `docs/superpowers/specs/2026-08-11-mvp-lancamento-fase1-design.md`.
- **Nenhuma migration.** A coluna `kb_root_page_id` permanece como está; documentos já ingeridos apontam para o root de `Products`, que continua na lista.
- **Fail-closed é inegociável.** Lista de roots vazia → `KnowledgeBaseConfigError` na descoberta e degradação para vazio/zero nas leituras. Nunca "sem filtro".
- **Nunca comparar `kb_root_page_id` com `None` via `==`** em consulta SQLAlchemy: compila para `IS NULL` e casa exatamente com os documentos sem procedência, que é o conjunto que o filtro existe para excluir.
- Ids do Notion sempre comparados na forma normalizada (`normalize_page_id`: sem hífen, minúsculo, sem espaços).
- Valor de env var começando com `#` é tratado como não configurado (convenção já existente em `_require_root`).
- Actions terminam em `Action` e expõem `execute()`; sem Service agregador (ADR-0004).
- Entities não importam SQLAlchemy, FastAPI nem Pydantic (ADR-0003).
- Comandos são descobertos automaticamente por existirem em `src/app/console/commands/`.
- Rodar testes: `pytest tests/caminho/test_x.py::test_nome -v`. A suíte de integração exige o Postgres com pgvector na porta configurada em `DB_PORT`.

**Allowlist de referência** (usada em `.env.example` e nas mensagens de exemplo):

```
23d8d655-c889-806d-8828-d527ce6a1529   Products
25c8d655-c889-8041-8c78-c300c4a2b496   Domínios & Subdomínios
2698d655-c889-8000-a6ea-d4a3316d44ab   Código de Cultura
2788d655-c889-8077-a9ae-c6bc20a281c8   Mapa Global de Papéis
2f48d655-c889-806d-a962-f30a85755687   Calendar 2026
```

`Borderless Coding Labs` e `Borderless Copy Bible` estão compartilhados com a integração mas **não** entram até Yuri confirmar (pendência registrada na spec). O comando `knowledge:roots` da Task 7 vai listá-los como drift — é o comportamento esperado, não um bug.

---

### Task 1: `Settings.kb_root_page_ids`

**Files:**
- Modify: `src/support/core/settings.py:41-46`
- Modify: `.env.example:27`
- Test: `tests/unit/support/core/test_settings_kb_root.py`

**Interfaces:**
- Consumes: `normalize_page_id(value: str | None) -> str | None` de `src.support.utils.notion_ids`
- Produces: `settings.NOTION_KB_ROOT_PAGE_IDS: str | None` e `settings.kb_root_page_ids -> tuple[str, ...]` (normalizados, deduplicados, na ordem de declaração)

- [ ] **Step 1: Write the failing test**

Substitua o conteúdo inteiro de `tests/unit/support/core/test_settings_kb_root.py`:

```python
from src.support.core.settings import Settings


def test_kb_root_page_ids_defaults_to_empty_tuple():
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_IDS is None
    assert s.kb_root_page_ids == ()


def test_kb_root_page_ids_splits_and_normalizes(monkeypatch):
    monkeypatch.setenv(
        "NOTION_KB_ROOT_PAGE_IDS",
        "23d8d655-c889-806d-8828-d527ce6a1529, 25C8D655C8898041-8C78C300C4A2B496",
    )
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == (
        "23d8d655c889806d8828d527ce6a1529",
        "25c8d655c88980418c78c300c4a2b496",
    )


def test_kb_root_page_ids_dedupes_preserving_order(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "abc-123, def456, ABC123")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ("abc123", "def456")


def test_kb_root_page_ids_ignores_blanks_and_commented_entries(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "abc123, , # desativado, def456")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ("abc123", "def456")


def test_kb_root_page_ids_empty_string_is_no_roots(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "   ")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/support/core/test_settings_kb_root.py -v`
Expected: FAIL com `AttributeError: 'Settings' object has no attribute 'NOTION_KB_ROOT_PAGE_IDS'`

- [ ] **Step 3: Write minimal implementation**

Em `src/support/core/settings.py`, adicione o import no topo do arquivo (junto dos demais imports):

```python
from src.support.utils.notion_ids import normalize_page_id
```

Substitua o bloco atual (linhas 44-46):

```python
    # Raiz da KB: a base é EXCLUSIVAMENTE o subtree deste folder do Notion
    # (folder "Products"). Sem ele, o sync aborta (ver NotionClient).
    NOTION_KB_ROOT_PAGE_ID: str | None = None
```

por:

```python
    # Raízes da KB: a base é EXCLUSIVAMENTE a união dos subtrees destes roots do
    # Notion, separados por vírgula. Eles são irmãos no nível do workspace — não
    # existe ancestral comum. Sem nenhum root, o sync aborta (ver NotionClient).
    NOTION_KB_ROOT_PAGE_IDS: str | None = None
```

E adicione a property ao final da classe `Settings`, antes de qualquer `model_config` que já exista no fim (se `model_config` estiver no topo, basta acrescentar ao final da classe):

```python
    @property
    def kb_root_page_ids(self) -> tuple[str, ...]:
        """Roots da KB normalizados, deduplicados, na ordem de declaração.

        Tupla vazia significa "sem escopo configurado" — os chamadores tratam
        isso como fail-closed (aborta na descoberta, devolve vazio na leitura),
        nunca como "sem filtro". Entrada iniciada por `#` é entrada comentada.
        """
        ids: list[str] = []
        for part in (self.NOTION_KB_ROOT_PAGE_IDS or "").split(","):
            if part.lstrip().startswith("#"):
                continue
            normalized = normalize_page_id(part)
            if normalized and normalized not in ids:
                ids.append(normalized)
        return tuple(ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/support/core/test_settings_kb_root.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Atualizar `.env.example`**

Substitua a linha 27 de `.env.example`:

```
NOTION_KB_ROOT_PAGE_ID=23d8d655-c889-806d-8828-d527ce6a1529
```

por:

```
# Roots da KB, separados por vírgula. São irmãos no nível do workspace do Notion.
# Products, Domínios & Subdomínios, Código de Cultura, Mapa Global de Papéis, Calendar 2026
NOTION_KB_ROOT_PAGE_IDS=23d8d655-c889-806d-8828-d527ce6a1529,25c8d655-c889-8041-8c78-c300c4a2b496,2698d655-c889-8000-a6ea-d4a3316d44ab,2788d655-c889-8077-a9ae-c6bc20a281c8,2f48d655-c889-806d-a962-f30a85755687
```

- [ ] **Step 6: Commit**

```bash
git add src/support/core/settings.py .env.example tests/unit/support/core/test_settings_kb_root.py
git commit -m "feat(kb): NOTION_KB_ROOT_PAGE_IDS aceita lista de roots"
```

---

### Task 2: Descoberta multi-root com procedência por página

**Files:**
- Modify: `src/support/clients/notion/notion_client.py:28-38` (dataclass `NotionPage`), `:113-132` (`list_approved_pages`, `_require_root`), `:158-192` (`_collect_scope`)
- Test: `tests/unit/support/clients/notion/test_notion_client_scope.py`

**Interfaces:**
- Consumes: `settings.kb_root_page_ids -> tuple[str, ...]` (Task 1)
- Produces:
  - `NotionPage.kb_root_page_id: str | None` — root normalizado sob o qual a página foi encontrada
  - `NotionClient._require_roots() -> tuple[str, ...]` (staticmethod, levanta `KnowledgeBaseConfigError` se vazio)
  - `NotionClient.list_approved_pages() -> list[NotionPage]` — união dos subtrees, sem duplicatas

- [ ] **Step 1: Write the failing test**

Acrescente ao final de `tests/unit/support/clients/notion/test_notion_client_scope.py`:

```python
def _make_multiroot_call(tree: dict[str, list[dict]], requested: list[str]):
    """Igual a `_make_call`, mas aceita ser chamado para vários roots."""

    async def call(tool: str, args: dict):
        assert tool == "API-get-block-children"
        block_id = args["block_id"]
        requested.append(block_id)
        return {"results": tree.get(block_id, []), "has_more": False}

    return call


@pytest.mark.asyncio
async def test_collect_scope_stamps_the_root_it_was_found_under():
    tree = {"rootA": [_child_page("A", "Programs")], "A": []}
    client = NotionClient()

    pages = await client._collect_scope(_make_call(tree, []), "rootA")

    assert [p.kb_root_page_id for p in pages] == ["roota"]


@pytest.mark.asyncio
async def test_list_approved_pages_unions_every_root(monkeypatch):
    tree = {
        "roota": [_child_page("A", "Programs")],
        "A": [],
        "rootb": [_child_page("B", "Código de Cultura")],
        "B": [],
    }
    requested: list[str] = []
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)
    client = NotionClient()
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_multiroot_call(tree, requested)),
    )

    pages = await client.list_approved_pages()

    assert {p.id for p in pages} == {"A", "B"}
    assert {p.id: p.kb_root_page_id for p in pages} == {"A": "roota", "B": "rootb"}


@pytest.mark.asyncio
async def test_page_reachable_from_two_roots_keeps_the_first_declared(monkeypatch):
    # "SHARED" é filha dos dois roots; vence o primeiro da ordem de declaração.
    tree = {
        "roota": [_child_page("SHARED", "Compartilhada")],
        "rootb": [_child_page("SHARED", "Compartilhada")],
        "SHARED": [],
    }
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)
    client = NotionClient()
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_multiroot_call(tree, [])),
    )

    pages = await client.list_approved_pages()

    assert len(pages) == 1
    assert pages[0].kb_root_page_id == "roota"


@pytest.mark.asyncio
async def test_list_approved_pages_raises_when_no_root_configured(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)

    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().list_approved_pages()
```

E acrescente este helper logo abaixo de `_make_call`, no topo do arquivo:

```python
def _fake_session(call):
    """Substitui `notion_mcp_session` por um contexto que devolve `call`."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session():
        yield call

    return session
```

Remova o teste antigo `test_list_approved_pages_raises_when_root_not_configured` — ele foi substituído por `test_list_approved_pages_raises_when_no_root_configured`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v`
Expected: FAIL — `AttributeError: 'NotionPage' object has no attribute 'kb_root_page_id'`

- [ ] **Step 3: Write minimal implementation**

Em `src/support/clients/notion/notion_client.py`, acrescente o campo ao dataclass `NotionPage` (depois de `section`):

```python
    kb_root_page_id: str | None = None  # root normalizado sob o qual foi achada
```

Substitua `list_approved_pages` e `_require_root` (linhas 113-132) por:

```python
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
```

Em `_collect_scope`, acrescente a etiqueta de procedência ao `NotionPage` construído (dentro do `approved.append(...)`, depois de `section=section`):

```python
                        kb_root_page_id=normalize_page_id(root_id),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/support/clients/notion/notion_client.py tests/unit/support/clients/notion/test_notion_client_scope.py
git commit -m "feat(kb): descoberta percorre todos os roots e etiqueta a procedência"
```

---

### Task 3: Ancestralidade multi-root no acesso avulso por id

**Files:**
- Modify: `src/support/clients/notion/notion_client.py:87-111` (`get_page_in_scope`), `:134-156` (`_is_in_scope` → `_find_root`)
- Test: `tests/unit/support/clients/notion/test_notion_client_ancestry.py`

**Interfaces:**
- Consumes: `NotionClient._require_roots()` (Task 2)
- Produces: `NotionClient._find_root(call, page_id, roots) -> str | None` — devolve o root normalizado que contém a página, ou `None`. Substitui `_is_in_scope`, que deixa de existir.
- `get_page_in_scope` passa a devolver `NotionPage` com `kb_root_page_id` preenchido com o root que casou.

- [ ] **Step 1: Write the failing test**

Substitua o corpo dos testes em `tests/unit/support/clients/notion/test_notion_client_ancestry.py` mantendo os helpers `_make_call` e `_page` do arquivo. Os testes novos:

```python
ROOTS = ("roota", "rootb")


@pytest.mark.asyncio
async def test_find_root_returns_the_matching_root_for_a_nested_page():
    pages = {
        "leaf": {"parent": {"type": "page_id", "page_id": "mid"}},
        "mid": {"parent": {"type": "page_id", "page_id": "rootB"}},
        "rootB": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "leaf", ROOTS) == "rootb"


@pytest.mark.asyncio
async def test_find_root_returns_the_root_itself():
    pages = {"rootA": {"parent": {"type": "workspace"}}}
    assert await NotionClient()._find_root(_make_call(pages), "rootA", ROOTS) == "roota"


@pytest.mark.asyncio
async def test_find_root_returns_none_for_a_sibling_outside_every_root():
    pages = {
        "sop": {"parent": {"type": "page_id", "page_id": "growth"}},
        "growth": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "sop", ROOTS) is None


@pytest.mark.asyncio
async def test_find_root_returns_none_for_a_database_row():
    pages = {"row": {"parent": {"type": "database_id", "database_id": "db"}}}
    assert await NotionClient()._find_root(_make_call(pages), "row", ROOTS) is None


@pytest.mark.asyncio
async def test_find_root_survives_a_parent_cycle():
    pages = {
        "a": {"parent": {"type": "page_id", "page_id": "b"}},
        "b": {"parent": {"type": "page_id", "page_id": "a"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "a", ROOTS) is None


@pytest.mark.asyncio
async def test_get_page_in_scope_raises_without_roots(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)

    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().get_page_in_scope("qualquer")
```

Garanta que o arquivo importe `KnowledgeBaseConfigError` e `settings`:

```python
from src.support.clients.notion.notion_client import KnowledgeBaseConfigError, NotionClient
from src.support.core.settings import settings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_ancestry.py -v`
Expected: FAIL — `AttributeError: 'NotionClient' object has no attribute '_find_root'`

- [ ] **Step 3: Write minimal implementation**

Substitua `_is_in_scope` (linhas 134-156) por:

```python
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
```

Substitua o corpo de `get_page_in_scope` (linhas 87-111) por:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_ancestry.py tests/unit/support/agent/test_tools_scope.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/support/clients/notion/notion_client.py tests/unit/support/clients/notion/test_notion_client_ancestry.py
git commit -m "feat(kb): acesso por id aceita qualquer root e devolve a procedência"
```

---

### Task 4: Sync grava a procedência da página e reconcilia root removido

**Files:**
- Modify: `src/domain/documents/actions/sync_knowledge_base_action.py:50-108`
- Test: `tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py`

**Interfaces:**
- Consumes: `NotionPage.kb_root_page_id` (Task 2), `settings.kb_root_page_ids` (Task 1)
- Produces: comportamento — todo documento ingerido recebe `kb_root_page_id` do root sob o qual sua página foi descoberta; documento cujo `kb_root_page_id` saiu da lista é soft-deletado no sync full.

- [ ] **Step 1: Write the failing test**

Em `tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py`, primeiro ajuste os dois helpers existentes para carregarem procedência.

`_approved` (linha 18) passa a aceitar o root:

```python
def _approved(
    page_id: str,
    edited: datetime,
    section: str | None = None,
    kb_root_page_id: str = "roota",
) -> NotionPage:
    return NotionPage(
        id=page_id, title=f"Doc {page_id}", content="", url="https://n", is_approved=True,
        last_edited_time=edited, section=section, kb_root_page_id=kb_root_page_id,
    )
```

`_existing` (linha 25) deixa de ler a env var e passa a receber o root, com o mesmo default:

```python
def _existing(
    page_id: str,
    edited: datetime | None,
    deleted: bool = False,
    kb_root_page_id: str = "roota",
) -> Document:
    """Documento já com provenência correta (mesmo root de `_approved`) por
    padrão — os testes que não são sobre provenância não devem disparar
    reingest por causa dela."""
    now = _dt(1)
    return Document(
        uuid=uuid4(), notion_page_id=page_id, title=f"Doc {page_id}", content="c",
        source_url="https://n", status="approved", created_at=now, updated_at=now,
        deleted_at=_dt(1) if deleted else None, last_edited_time=edited,
        kb_root_page_id=kb_root_page_id,
    )
```

Como todos os testes do arquivo passam a depender da allowlist, acrescente uma fixture autouse logo abaixo dos imports:

```python
@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)
```

Se `normalize_page_id` ficar sem uso no arquivo depois disso, remova o import. As linhas 192 e 212, que hoje fazem `monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", "23d8...")`, ficam redundantes com a fixture — remova-as.

Agora acrescente os dois testes novos ao final do arquivo:

```python
@pytest.mark.asyncio
async def test_ingests_each_page_under_its_own_root():
    notion = FakeNotion([
        _approved("a", _dt(5), kb_root_page_id="roota"),
        _approved("b", _dt(5), kb_root_page_id="rootb"),
    ])
    ingest = FakeIngest()

    await _action(notion, ingest, FakeDocRepo([]), FakeChunkRepo()).execute()

    # FakeNotion.get_page devolve um NotionPage novo, sem procedência — é
    # exatamente por isso que a action precisa copiar o root da página
    # descoberta para a página completa antes de mapear.
    assert {d.notion_page_id: d.kb_root_page_id for d in ingest.documents} == {
        "a": "roota",
        "b": "rootb",
    }


@pytest.mark.asyncio
async def test_soft_deletes_documents_whose_root_left_the_allowlist():
    # A página nem aparece mais na descoberta, e sua procedência é de um root
    # que saiu da allowlist — os dois motivos de saída de escopo.
    docs = FakeDocRepo([_existing("z", _dt(5), kb_root_page_id="rootremovido")])
    chunks = FakeChunkRepo()

    report = await _action(FakeNotion([]), FakeIngest(), docs, chunks).execute()

    assert report.removed == 1
    assert docs.soft_deleted == ["z"]
    assert chunks.cleared != []


@pytest.mark.asyncio
async def test_soft_deletes_a_still_approved_page_whose_root_was_dropped():
    # Caso que a lista de aprovados NÃO revela: a página continua sendo
    # descoberta, mas sob um root fora da allowlist vigente.
    notion = FakeNotion([_approved("y", _dt(5), kb_root_page_id="rootfora")])
    docs = FakeDocRepo([_existing("y", _dt(5), kb_root_page_id="rootfora")])

    report = await _action(notion, FakeIngest(), docs, FakeChunkRepo()).execute()

    assert docs.soft_deleted == ["y"]
    assert report.removed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py -v`
Expected: FAIL — os documentos ingeridos saem com `kb_root_page_id` vindo de `settings.NOTION_KB_ROOT_PAGE_ID`, que não existe mais

- [ ] **Step 3: Write minimal implementation**

Em `src/domain/documents/actions/sync_knowledge_base_action.py`, remova a linha 52 (`root_page_id = settings.NOTION_KB_ROOT_PAGE_ID or ""`) e substitua por:

```python
        roots = set(settings.kb_root_page_ids)
```

Dentro do laço, substitua a cláusula de auto-cura (linhas 72-81) por:

```python
                # Auto-cura: se a provenência gravada não bate com o root sob o
                # qual a página foi descoberta agora (ex.: coluna NULL logo após
                # a migração 0004, ou página que mudou de root), reingere mesmo
                # sem --force. Sem isso, um sync incremental nunca re-stampa
                # `kb_root_page_id` e o retrieval filtrado por root passa a
                # devolver [] pra sempre.
                or (
                    current is not None
                    and normalize_page_id(current.kb_root_page_id)
                    != normalize_page_id(page.kb_root_page_id)
                )
```

Substitua a chamada ao mapper (linhas 88-90) por:

```python
                        full.kb_root_page_id = page.kb_root_page_id
                        await self.ingest.execute(
                            NotionPageMapper.to_document(full, page.kb_root_page_id or "")
                        )
```

E substitua a reconciliação (linhas 100-106) por:

```python
        if not partial:
            now = datetime.now(timezone.utc)
            for page_id, doc in existing.items():
                if doc.deleted_at is not None:
                    continue
                # Dois motivos para sair do escopo: a página não apareceu em
                # nenhuma travessia, ou o root sob o qual ela foi ingerida não
                # está mais na allowlist. O segundo caso não é observável pela
                # lista de aprovados — só pela procedência gravada.
                left_scope = page_id not in approved_ids or (
                    normalize_page_id(doc.kb_root_page_id) not in roots
                )
                if left_scope:
                    await self.documents.soft_delete_by_page_id(page_id, now)
                    await self.chunks.replace_for_document(doc.uuid, [])
                    report.removed += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/documents/actions/sync_knowledge_base_action.py tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py
git commit -m "feat(kb): sync grava procedência por página e reconcilia root removido"
```

---

### Task 5: Recuperação filtra por pertencimento ao conjunto de roots

**Files:**
- Modify: `src/domain/documents/repositories/document_chunk_repository.py:31`, `:86`, `:113`
- Modify: `src/domain/documents/repositories/document_repository.py:74`, `:105`, `:135`
- Test: `tests/integration/domain/documents/test_chunk_repository_scope_filter.py`, `tests/integration/domain/documents/test_list_knowledge_sections.py`

**Interfaces:**
- Consumes: `settings.kb_root_page_ids` (Task 1)
- Produces: as seis consultas passam a usar `DocumentModel.kb_root_page_id.in_(roots)`; sem roots, degradam para `[]`/`None`/`0` como hoje.

- [ ] **Step 1: Write the failing test**

Em `tests/integration/domain/documents/test_chunk_repository_scope_filter.py`, acrescente:

```python
@pytest.mark.asyncio
async def test_search_similar_returns_documents_from_every_configured_root(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(
        settings, "NOTION_KB_ROOT_PAGE_IDS", f"{ROOT},{OUTRO_ROOT}", raising=False
    )
    await seed_document_with_chunk(title="Do root A", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Do root B", kb_root_page_id=OUTRO_ROOT)

    results = await DocumentChunkRepository().search_similar([0.0] * settings.EMBEDDING_DIM)

    assert {r.citation.title for r in results} == {"Do root A", "Do root B"}


@pytest.mark.asyncio
async def test_search_similar_excludes_root_outside_the_allowlist(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    await seed_document_with_chunk(title="Dentro", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Fora", kb_root_page_id=OUTRO_ROOT)

    results = await DocumentChunkRepository().search_similar([0.0] * settings.EMBEDDING_DIM)

    assert {r.citation.title for r in results} == {"Dentro"}
```

Nos dois arquivos de teste, troque todos os `monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ...)` por `NOTION_KB_ROOT_PAGE_IDS`. O teste que hoje garante que documento com `kb_root_page_id=None` não é recuperado **permanece como está** — ele continua sendo a proteção contra a armadilha do `IS NULL`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/domain/documents/test_chunk_repository_scope_filter.py -v`
Expected: FAIL — `search_similar` devolve `[]`, porque `settings.NOTION_KB_ROOT_PAGE_ID` não existe mais e a guarda `root is None` dispara

- [ ] **Step 3: Write minimal implementation**

Nos dois repositórios, em cada um dos seis pontos, substitua o par guarda + filtro. O padrão antigo:

```python
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            return <degradado>
```

vira:

```python
        roots = settings.kb_root_page_ids
        if not roots:
            return <degradado>
```

e o filtro dentro do `.where(...)`:

```python
                DocumentModel.kb_root_page_id == root,
```

vira:

```python
                DocumentModel.kb_root_page_id.in_(roots),
```

O valor degradado é diferente em cada método e **precisa ser preservado exatamente**:

| Arquivo | Linha | Método | Degradado |
|---|---|---|---|
| `document_chunk_repository.py` | 31 | `search_similar` | `[]` |
| `document_chunk_repository.py` | 86 | `nearest_distance` | `None` |
| `document_chunk_repository.py` | 113 | `count_in_scope` | `0` |
| `document_repository.py` | 74 | `list_sections` | `[]` |
| `document_repository.py` | 105 | contagem de aprovados ativos | `0` |
| `document_repository.py` | 135 | contagem de removidos | `0` |

Atualize o comentário-guarda longo que existe em `search_similar` e em `list_sections` para refletir o conjunto:

```python
            # Guarda deliberada, não simplificar: `DocumentModel.kb_root_page_id
            # == None` compila para `WHERE kb_root_page_id IS NULL`, que combina
            # exatamente com os documentos sem procedência — o conjunto que este
            # filtro existe para excluir. `IN` já exclui NULL naturalmente, mas a
            # guarda continua necessária: `IN ()` sem roots seria SQL inválido, e
            # sem roots a leitura precisa degradar para "sem conhecimento" em vez
            # de expor tudo.
```

Se `normalize_page_id` ficar sem uso em algum dos dois arquivos, remova o import.

- [ ] **Step 3b: Migrar os arquivos de teste de integração restantes**

Estes cinco arquivos fazem `monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ...)` e passam a usar `NOTION_KB_ROOT_PAGE_IDS`, sem outra mudança — o valor continua sendo um único id, agora lido como lista de um elemento:

- `tests/integration/domain/documents/test_ingest_document_action.py` (linhas 28, 95)
- `tests/integration/domain/documents/test_count_knowledge_base_action.py` (linhas 20, 36, 51, 67)
- `tests/integration/domain/documents/test_chunk_repository_threshold.py` (linhas 14, 33)
- `tests/integration/domain/documents/test_document_chunk_repository.py` (linhas 28, 61)
- `tests/integration/domain/documents/test_chunk_repository_nearest.py` (linhas 19, 34, 41, 53)

Atenção a um detalhe: os testes que passam `None` para simular "sem root configurado" continuam válidos — `settings.kb_root_page_ids` devolve `()` e a guarda dispara igual.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/domain/documents -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/documents/repositories/ tests/integration/domain/documents/
git commit -m "feat(kb): recuperação filtra por pertencimento ao conjunto de roots"
```

---

### Task 6: Comandos e seed migrados para a lista de roots

**Files:**
- Modify: `src/app/console/commands/knowledge_ingest_command.py:38`
- Modify: `src/app/console/commands/knowledge_calibrate_command.py:54-57`
- Modify: `database/seeds/dev_documents_seed.py:36`
- Test: `tests/unit/app/console/test_knowledge_ingest_command.py`

**Interfaces:**
- Consumes: `NotionPage.kb_root_page_id` (Task 3), `settings.kb_root_page_ids` (Task 1)
- Produces: nenhuma interface nova; alinha os últimos consumidores da env var singular.

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/unit/app/console/test_knowledge_ingest_command.py` um teste do caminho feliz — o existente só cobre a recusa. Ele prova que a procedência gravada vem da **página**, não da env var:

```python
@pytest.mark.asyncio
async def test_persists_the_root_that_contains_the_page(monkeypatch):
    """Com vários roots, a env var não diz sob qual deles esta página está —
    só `get_page_in_scope` sabe, porque foi ela que subiu a ancestralidade."""

    class _FakeNotionInScope:
        async def get_page_in_scope(self, page_id: str):
            return NotionPage(
                id=page_id, title="Página", content="corpo", url="https://n",
                is_approved=True, last_edited_time=None, kb_root_page_id="rootb",
            )

    captured: list = []

    class _FakeIngest:
        def __init__(self, embeddings=None) -> None:
            self.embeddings = embeddings

        async def execute(self, document):
            captured.append(document)
            return document

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    module = "src.app.console.commands.knowledge_ingest_command"
    monkeypatch.setattr(f"{module}.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(f"{module}.IngestDocumentAction", _FakeIngest)
    monkeypatch.setattr(f"{module}.get_embeddings_client", lambda: None)

    command = KnowledgeIngestCommand(notion=_FakeNotionInScope())
    command.input = {"page_id": "p1"}

    await command.handle()

    assert captured[0].kb_root_page_id == "rootb"
```

Acrescente o import de `NotionPage` no topo do arquivo:

```python
from src.support.clients.notion.notion_client import NotionPage
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/app/console/test_knowledge_ingest_command.py -v`
Expected: FAIL — `NotionPage.__init__() got an unexpected keyword argument 'kb_root_page_id'` se a Task 2 não estiver aplicada; com ela aplicada, falha na afirmação porque o comando ainda lê a env var singular

- [ ] **Step 3: Write minimal implementation**

Em `knowledge_ingest_command.py`, substitua a linha 38:

```python
                root_page_id = settings.NOTION_KB_ROOT_PAGE_ID or ""
```

por:

```python
                # A procedência vem da página (o root que a contém, resolvido por
                # `get_page_in_scope`), não da env var: com vários roots, a env
                # var não diz sob qual deles esta página está.
                root_page_id = page.kb_root_page_id or ""
```

Em `knowledge_calibrate_command.py`, substitua as linhas 54-57:

```python
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            print("NOTION_KB_ROOT_PAGE_ID não configurado — nada a calibrar.")
            return
```

por:

```python
        if not settings.kb_root_page_ids:
            print("NOTION_KB_ROOT_PAGE_IDS não configurado — nada a calibrar.")
            return
```

Se `normalize_page_id` deixar de ser usado nesse arquivo, remova o import.

Em `database/seeds/dev_documents_seed.py:36`, substitua:

```python
                kb_root_page_id=normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID),
```

por:

```python
                # Primeiro root da allowlist: o seed de dev só precisa de uma
                # procedência válida para o documento ser recuperável.
                kb_root_page_id=next(iter(settings.kb_root_page_ids), None),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/app/console -v && grep -rn "NOTION_KB_ROOT_PAGE_ID\b" src/ database/ | grep -v "NOTION_KB_ROOT_PAGE_IDS"`
Expected: PASS nos testes, e o `grep` **sem nenhuma saída** — nenhuma referência à env var singular sobrou no código de produção

- [ ] **Step 5: Commit**

```bash
git add src/app/console/commands/ database/seeds/dev_documents_seed.py tests/unit/app/console/
git commit -m "refactor(kb): comandos e seed consomem a lista de roots"
```

---

### Task 7: `DetectKbRootDriftAction` e o comando `knowledge:roots`

**Files:**
- Create: `src/domain/documents/dtos/kb_root_drift.py`
- Create: `src/domain/documents/actions/detect_kb_root_drift_action.py`
- Create: `src/app/console/commands/knowledge_roots_command.py`
- Modify: `src/support/clients/notion/notion_client.py` (novo método `list_workspace_root_pages`)
- Modify: `src/domain/documents/actions/__init__.py`
- Test: `tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py`

**Interfaces:**
- Consumes: `settings.kb_root_page_ids` (Task 1)
- Produces:
  - `WorkspaceRootPage` — dataclass com `id: str` (normalizado) e `title: str`
  - `NotionClient.list_workspace_root_pages() -> list[WorkspaceRootPage]`
  - `KbRootDrift` — dataclass com `unlisted: list[WorkspaceRootPage]` e `missing: list[str]`, e property `has_drift: bool`
  - `DetectKbRootDriftAction.execute() -> KbRootDrift`

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py`:

```python
import pytest

from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.support.clients.notion.notion_client import WorkspaceRootPage
from src.support.core.settings import settings


class _FakeNotion:
    def __init__(self, pages: list[WorkspaceRootPage]) -> None:
        self._pages = pages

    async def list_workspace_root_pages(self) -> list[WorkspaceRootPage]:
        return self._pages


@pytest.mark.asyncio
async def test_reports_pages_visible_but_absent_from_the_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    notion = _FakeNotion([
        WorkspaceRootPage(id="abc123", title="Products"),
        WorkspaceRootPage(id="def456", title="Borderless Copy Bible"),
    ])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert [p.title for p in drift.unlisted] == ["Borderless Copy Bible"]
    assert drift.missing == []
    assert drift.has_drift is True


@pytest.mark.asyncio
async def test_reports_allowlisted_roots_the_integration_cannot_see(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123,ghi789", raising=False)
    notion = _FakeNotion([WorkspaceRootPage(id="abc123", title="Products")])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert drift.unlisted == []
    assert drift.missing == ["ghi789"]
    assert drift.has_drift is True


@pytest.mark.asyncio
async def test_no_drift_when_allowlist_matches_visibility(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    notion = _FakeNotion([WorkspaceRootPage(id="abc123", title="Products")])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert drift.unlisted == []
    assert drift.missing == []
    assert drift.has_drift is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py -v`
Expected: FAIL — `ModuleNotFoundError: src.domain.documents.actions.detect_kb_root_drift_action`

- [ ] **Step 3: Write minimal implementation**

Em `src/support/clients/notion/notion_client.py`, acrescente o dataclass junto de `NotionPage`:

```python
@dataclass
class WorkspaceRootPage:
    """Página no nível do workspace visível à integração. Id já normalizado."""

    id: str
    title: str
```

e o método público, logo depois de `list_approved_pages`:

```python
    async def list_workspace_root_pages(self) -> list[WorkspaceRootPage]:
        """Páginas de nível de workspace que a integração enxerga.

        É a superfície de permissão do lado do Notion — o que a dona do produto
        liberou. Comparar com a allowlist é o que revela drift; este método não
        aplica escopo nenhum, de propósito.
        """
        pages: list[WorkspaceRootPage] = []
        async with notion_mcp_session() as call:
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
                        pages.append(
                            WorkspaceRootPage(id=page_id, title=_extract_title(page))
                        )
                if not data.get("has_more"):
                    return pages
                cursor = data.get("next_cursor")
```

Crie `src/domain/documents/dtos/kb_root_drift.py`:

```python
from dataclasses import dataclass, field

from src.support.clients.notion.notion_client import WorkspaceRootPage


@dataclass
class KbRootDrift:
    """Diferença entre a allowlist de roots e o que a integração enxerga.

    `unlisted`: liberado no Notion mas fora da allowlist — alguém liberou algo e
    o oráculo ainda não lê. `missing`: na allowlist mas invisível — permissão
    revogada, página movida, ou id errado na env var.
    """

    unlisted: list[WorkspaceRootPage] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.unlisted or self.missing)
```

Crie `src/domain/documents/actions/detect_kb_root_drift_action.py`:

```python
from src.domain.documents.dtos.kb_root_drift import KbRootDrift
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.settings import settings


class DetectKbRootDriftAction:
    """Compara a allowlist de roots com o que a integração do Notion enxerga.

    Existe para substituir o aviso humano ("te aviso quando liberar mais coisa")
    por um sinal do sistema. Não altera a allowlist: incluir um root novo
    continua sendo decisão humana, feita na variável de ambiente.
    """

    def __init__(self, notion=None) -> None:
        self.notion = notion or NotionClient()

    async def execute(self) -> KbRootDrift:
        allowlist = set(settings.kb_root_page_ids)
        visible = await self.notion.list_workspace_root_pages()
        visible_ids = {page.id for page in visible}
        return KbRootDrift(
            unlisted=[page for page in visible if page.id not in allowlist],
            missing=[root for root in settings.kb_root_page_ids if root not in visible_ids],
        )
```

Exporte a Action em `src/domain/documents/actions/__init__.py`, seguindo o padrão das existentes (import + entrada em `__all__`).

Crie `src/app/console/commands/knowledge_roots_command.py`:

```python
from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.support.core.console.command import Command
from src.support.core.settings import settings


class KnowledgeRootsCommand(Command):
    signature = "knowledge:roots"
    description = (
        "Compara os roots configurados da KB com as páginas que a integração do "
        "Notion enxerga no workspace. Reporta drift nos dois sentidos."
    )

    def __init__(self, action: DetectKbRootDriftAction | None = None) -> None:
        super().__init__()
        # Injetável em teste; o autodiscovery do kernel instancia sem argumentos.
        self._action = action or DetectKbRootDriftAction()

    async def handle(self) -> None:
        drift = await self._action.execute()

        print(f"Roots configurados: {len(settings.kb_root_page_ids)}")
        for root in settings.kb_root_page_ids:
            print(f"  - {root}")

        if drift.unlisted:
            print("\nVisíveis à integração mas FORA da allowlist:")
            for page in drift.unlisted:
                print(f"  ! {page.id}  {page.title}")
            print("\n  Para incluir, acrescente o id a NOTION_KB_ROOT_PAGE_IDS.")

        if drift.missing:
            print("\nNa allowlist mas INVISÍVEIS à integração:")
            for root in drift.missing:
                print(f"  ! {root}")
            print("\n  Permissão revogada, página movida, ou id errado na env var.")

        if not drift.has_drift:
            print("\nSem drift: allowlist e visibilidade coincidem.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py -v && python cli.py knowledge:roots --help`
Expected: PASS nos testes, e o comando aparece no autodiscovery

- [ ] **Step 5: Commit**

```bash
git add src/domain/documents/dtos/kb_root_drift.py src/domain/documents/actions/ src/app/console/commands/knowledge_roots_command.py src/support/clients/notion/notion_client.py tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py
git commit -m "feat(kb): comando knowledge:roots reporta drift da allowlist"
```

---

### Task 8: Sync avisa sobre drift sozinho

**Files:**
- Modify: `src/app/console/jobs/sync_knowledge_base_job.py`
- Test: `tests/unit/app/console/test_sync_knowledge_base_job_drift.py`

**Interfaces:**
- Consumes: `DetectKbRootDriftAction.execute() -> KbRootDrift` (Task 7)
- Produces: nenhuma interface nova; o job emite WARNING quando há root liberado fora da allowlist.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/app/console/test_sync_knowledge_base_job_drift.py`:

```python
import logging

import pytest

from src.app.console.jobs.sync_knowledge_base_job import SyncKnowledgeBaseJob
from src.domain.documents.dtos.kb_root_drift import KbRootDrift
from src.support.clients.notion.notion_client import WorkspaceRootPage


class _FakeDriftAction:
    def __init__(self, drift: KbRootDrift) -> None:
        self._drift = drift

    async def execute(self) -> KbRootDrift:
        return self._drift


@pytest.mark.asyncio
async def test_warns_when_a_liberated_root_is_outside_the_allowlist(caplog):
    drift = KbRootDrift(
        unlisted=[WorkspaceRootPage(id="def456", title="Borderless Copy Bible")]
    )

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(drift))

    assert "Borderless Copy Bible" in caplog.text


@pytest.mark.asyncio
async def test_stays_quiet_without_drift(caplog):
    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(KbRootDrift()))

    assert caplog.text == ""


@pytest.mark.asyncio
async def test_drift_failure_never_breaks_the_sync(caplog):
    class _Explodes:
        async def execute(self):
            raise RuntimeError("MCP fora do ar")

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_Explodes())  # não levanta
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/app/console/test_sync_knowledge_base_job_drift.py -v`
Expected: FAIL — `AttributeError: 'SyncKnowledgeBaseJob' object has no attribute '_warn_on_drift'`

- [ ] **Step 3: Write minimal implementation**

Substitua `src/app/console/jobs/sync_knowledge_base_job.py` por:

```python
import logging

from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.actions.sync_knowledge_base_action import SyncKnowledgeBaseAction
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.scheduling import Job

logger = logging.getLogger(__name__)


class SyncKnowledgeBaseJob(Job):
    """Refresh incremental da base de conhecimento (Notion → pgvector).

    Idempotente: só reingere páginas novas/editadas e remove as que saíram do
    escopo aprovado. A `Job.execute` já provê sessão + advisory lock + tracking.
    """

    async def action(self) -> None:
        result = await SyncKnowledgeBaseAction(
            notion=NotionClient(),
            ingest=IngestDocumentAction(embeddings=get_embeddings_client()),
        ).execute()
        logger.info("SyncKnowledgeBaseJob: %s", result)
        await self._warn_on_drift(DetectKbRootDriftAction())

    @staticmethod
    async def _warn_on_drift(action) -> None:
        """Avisa quando existe root liberado no Notion fora da allowlist.

        É o sinal que substitui o aviso humano. Falha aqui nunca derruba o
        sync: o refresh da base já aconteceu e vale mais que o diagnóstico.
        """
        try:
            drift = await action.execute()
        except Exception:  # observabilidade não derruba o job
            logger.warning("não foi possível checar drift de roots", exc_info=True)
            return
        for page in drift.unlisted:
            logger.warning(
                "root liberado no Notion e fora de NOTION_KB_ROOT_PAGE_IDS: %s (%s)",
                page.title,
                page.id,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/app/console/test_sync_knowledge_base_job_drift.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/console/jobs/sync_knowledge_base_job.py tests/unit/app/console/test_sync_knowledge_base_job_drift.py
git commit -m "feat(kb): sync avisa sobre root liberado fora da allowlist"
```

---

### Task 9: ADR-0014, mapa de arquitetura e documentação

**Files:**
- Create: `docs/adr/0014-kb-multi-root.md`
- Modify: `docs/adr/README.md` (índice)
- Modify: `frontend/src/features/ops/architectureMap.ts:35`, `:108`
- Modify: `CLAUDE.md` (se mencionar `NOTION_KB_ROOT_PAGE_ID`)

**Interfaces:**
- Consumes: comportamento das Tasks 1-8
- Produces: nenhuma interface de código.

- [ ] **Step 1: Escrever o ADR-0014**

Crie `docs/adr/0014-kb-multi-root.md` seguindo o template dos existentes — `## Status`, `## Resumo` com **Decisão** / **Aplica-se quando** / **Regra prática**, `---`, e o corpo. Conteúdo:

- **Status:** Aceito — 2026-08-11. Substitui o ADR-0011.
- **Decisão:** a KB é a união dos subtrees de `NOTION_KB_ROOT_PAGE_IDS`. Cada documento registra o root sob o qual foi descoberto; recuperação e acesso por id validam pertencimento ao conjunto.
- **Aplica-se quando:** mexer em escopo da KB, ingestão/sync, recuperação, ou em qualquer tool que leia o Notion por id.
- **Regra prática:** escopo continua invariante de leitura. Documento cujo `kb_root_page_id` não está entre os roots atuais não é recuperado nem citado. Lista vazia é fail-closed.
- **Contexto:** o ADR-0011 assumiu um root único porque a KB era o folder "Products". Na reunião de 06/08 a curadoria passou para o lado do Notion e as páginas liberadas são irmãs no nível do workspace — não existe ancestral comum, então um root único não consegue expressar o escopo. Registre também que o ADR-0012 continua valendo, com `== root` lido agora como `∈ roots`.
- **Consequências:** a env var singular deixa de existir; a atribuição de root para página alcançável por dois roots é o primeiro da ordem de declaração; drift entre allowlist e permissão do Notion vira sinal explícito (`knowledge:roots` e WARNING no sync) em vez de aviso humano.

Acrescente a linha do ADR-0014 na tabela "Índice de ADRs" em `docs/adr/README.md` e marque o ADR-0011 como substituído, seguindo a convenção já usada no arquivo.

- [ ] **Step 2: Corrigir o mapa de arquitetura**

Em `frontend/src/features/ops/architectureMap.ts`, linha 35, substitua:

```ts
        description: "Lê o subtree do folder Products via MCP. Fora do root, nada é visitado.",
```

por:

```ts
        description: "Lê o subtree de cada root liberado via MCP. Fora dos roots, nada é visitado.",
```

E na linha 108, substitua:

```ts
        description: "Top-k no pgvector, escopado ao root, cortado pela distância máxima.",
```

por:

```ts
        description: "Top-k no pgvector, escopado aos roots, cortado pela distância máxima.",
```

- [ ] **Step 3: Alinhar o CLAUDE.md**

Rode `grep -n "NOTION_KB_ROOT_PAGE_ID" CLAUDE.md docs/*.md`. Onde a env var singular aparecer, troque pela plural e ajuste a frase de "subtree do folder Products" para "união dos subtrees dos roots liberados".

- [ ] **Step 4: Rodar a suíte inteira e varrer a env var antiga**

Run:

```bash
pytest && grep -rn "NOTION_KB_ROOT_PAGE_ID\b" . \
  --include=*.py --include=*.md --include=*.example --include=*.ts \
  | grep -v node_modules | grep -v "docs/adr/001"
```

Expected: `pytest` PASS, e o `grep` **sem nenhuma saída**. Os ADRs 0011 e 0012 são imutáveis e mantêm a env var singular no texto histórico — por isso ficam de fora da varredura.

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS. `architectureMap.test.ts` continua passando — nenhum arquivo declarado no mapa foi renomeado ou removido.

- [ ] **Step 5: Verificar `alembic check`**

Run: `alembic check`
Expected: sem diferenças pendentes — este plano não altera nenhum model.

- [ ] **Step 6: Commit**

```bash
git add docs/adr/0014-kb-multi-root.md docs/adr/README.md frontend/src/features/ops/architectureMap.ts CLAUDE.md
git commit -m "docs(kb): ADR-0014 substitui o 0011 e alinha mapa de arquitetura"
```
