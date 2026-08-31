# Escopo da KB descoberto pelo MCP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar a allowlist de roots em variável de ambiente pela superfície de permissão da integração do Notion — o que o Yuri compartilha é o que o oráculo lê.

**Architecture:** `NotionClient.list_approved_pages` passa a descobrir os roots via `API-post-search` (páginas de nível de workspace) em vez de ler `settings.kb_root_page_ids`; a travessia por subárvore, a curadoria e a reconciliação ficam idênticas. O filtro de escopo sai das seis consultas de recuperação, e a checagem de ancestralidade na leitura por id deixa de autorizar e passa só a derivar procedência — com a `KnowledgeCurationPolicy` assumindo, explicitamente, a recusa que a ancestralidade fazia por acidente.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, pytest/pytest-asyncio, Notion via MCP, pgvector.

**Spec:** [`docs/superpowers/specs/2026-08-31-kb-escopo-descoberto-design.md`](../specs/2026-08-31-kb-escopo-descoberto-design.md)

## Global Constraints

- **A `KnowledgeCurationPolicy` não muda em nenhuma task.** Linha de banco (`data_source_id` / `database_id`) e denylist de títulos continuam exatamente como estão. É ela que sustenta a regra inegociável nº 4 depois desta mudança — quem mexer nela saiu do escopo do plano.
- **Sem migration.** Nenhuma coluna é criada, alterada ou removida; `kb_root_page_id` continua existindo e sendo preenchida. `alembic check` tem de continuar limpo sem revisão nova.
- **TDD obrigatório.** Toda task começa por teste que falha pelo motivo certo. Testes que hoje afirmam a garantia antiga são **reescritos**, nunca deletados sem substituto — exceto os dois casos em que o objeto testado deixa de existir (Task 6 e Task 7), explicitamente marcados.
- **Banco de teste em `DB_PORT=5434`** (pgvector local; a porta 5432 tem conflito nesta máquina). Os testes de integração leem `DB_PORT` do `.env`.
- **Commits em português**, conventional commits, terminando com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Ordem das tasks importa.** A Task 7 remove `Settings.kb_root_page_ids`; ela só pode rodar depois que as Tasks 2–6 removeram todos os leitores. Rodar fora de ordem quebra o import.
- Regras do `CLAUDE.md` valem integralmente: domain não importa HTTP, Entity ≠ Model, sessão vem do contexto, controllers finos.

---

### Task 1: ADR-0015 — registrar a decisão antes do código

O `CLAUDE.md` exige ADR **antes** da implementação para decisão que contraria regra existente. Esta contraria três ADRs aceitos.

**Files:**
- Create: `docs/adr/0015-kb-escopo-descoberto-pela-permissao.md`
- Modify: `docs/adr/README.md` (tabela "Índice de ADRs")

**Interfaces:**
- Consumes: nada.
- Produces: o número `ADR-0015`, citado nos docstrings e comentários das Tasks 2–7.

- [x] **Step 1: Escrever o ADR**

Criar `docs/adr/0015-kb-escopo-descoberto-pela-permissao.md` seguindo o template do `docs/adr/README.md` (`## Status`, `## Resumo` com três blocos, `---`, corpo):

```markdown
# ADR-0015 — Escopo da KB descoberto pela permissão do Notion

## Status

Aceito — 2026-08-31. Substitui o [ADR-0011](0011-kb-restrita-root-notion.md) e o
[ADR-0014](0014-kb-multi-root.md); substitui a metade de leitura do
[ADR-0012](0012-escopo-kb-aplicado-na-recuperacao.md).

## Resumo

- **Decisão:** os roots da KB deixam de vir de variável de ambiente e passam a
  ser todas as páginas de nível de workspace que a integração do Notion
  enxerga, descobertas a cada sync via `API-post-search`. O filtro de escopo
  sai da recuperação; a leitura por id recusa por curadoria, não por
  ancestralidade.
- **Aplica-se quando:** mexer em escopo da KB, ingestão/sync, recuperação, ou
  em qualquer caminho que leia o Notion por id.
- **Regra prática:** o que a integração enxerga é o escopo. Não existe segunda
  lista para manter em sincronia. Quem decide se uma página é ingerível é a
  `KnowledgeCurationPolicy` — e ela precisa ser checada explicitamente em todo
  caminho de leitura por id.

---

## Contexto

O ADR-0014 implementou o pedido da reunião de 06/08 ("já limitei o escopo pra
você, pode puxar tudo que o MCP está entregando") como allowlist explícita de
roots em `NOTION_KB_ROOT_PAGE_IDS`. A [spec da Fase 1](../superpowers/specs/2026-08-11-mvp-lancamento-fase1-design.md)
registrou, na própria época, que "o que ele liberou e o que ele descreveu não
coincidem exatamente" e deixou a allowlist final pendente de confirmação.

A pendência é estrutural, não operacional. A allowlist obriga uma ida e volta
humana — o Yuri libera uma pasta, avisa, alguém edita a env var, alguém faz
deploy — toda vez que a curadoria muda. O `DetectKbRootDriftAction` foi
construído para tornar essa divergência visível, o que é a confissão de que ela
existe por construção: duas listas descrevendo a mesma intenção sempre
divergem.

## Decisão

O escopo da KB é a superfície de permissão da integração do Notion. Os roots
são descobertos a cada sync; a travessia por subárvore, a curadoria e a
reconciliação não mudam.

Três consequências diretas:

1. **Recuperação sem filtro de root.** O filtro de leitura do ADR-0012 existia
   para compensar um escopo *de configuração* que podia divergir do escopo *de
   permissão*. Quando o escopo é a permissão, não há o que divergir.
2. **Leitura por id recusa por curadoria.** A subida de `parent` deixa de
   autorizar e passa a derivar procedência (`kb_root_page_id`). A recusa que
   ela fazia por acidente — linha de banco tem `parent.type == "database_id"` e
   devolvia `None` — passa a ser feita explicitamente pela
   `KnowledgeCurationPolicy`.
3. **Fail-closed só na descoberta vazia.** Zero páginas de topo visíveis não
   significa "o Yuri despublicou tudo": significa token revogado ou MCP fora do
   ar. O sync aborta em vez de reconciliar, porque reconciliar apagaria a base
   inteira numa rodada.

## Consequências

**Positivas.** Uma lista a menos para manter em sincronia; liberar conteúdo
passa a ser ação única do lado do Notion, com efeito no sync seguinte; a
proteção contra PII fica num lugar só e explícito, em vez de depender de um
efeito colateral da travessia de ancestralidade.

**Negativas, aceitas.** Despublicar uma página deixa de ter efeito imediato: ela
continua recuperável e citável até o próximo sync rodar — antes, trocar a env
var valia na hora. E o time perde o freio de configuração: não há mais como
excluir uma página do lado do código sem pedir ao Notion.

**Neutra.** `kb_root_page_id` continua preenchida e verdadeira, mas deixa de
gatilhar decisão de acesso: vira procedência para diagnóstico
(`knowledge:roots`) e para a auto-cura do sync.

## Alternativas consideradas

**Persistir o conjunto descoberto numa tabela e continuar filtrando a
recuperação contra ela.** Recuperaria a garantia de leitura apenas na janela
que a própria reconciliação já fecha a cada sync, ao custo de uma migration, um
repositório e um modo de falha novo e pior: tabela vazia no bootstrap filtraria
tudo, e o oráculo subiria mudo sem nada ligar o sintoma à causa.

**Busca plana: ingerir toda página que o `search` devolve, em qualquer nível.**
É a leitura literal de "tudo", e foi a descoberta original que o ADR-0012
removeu. Perde `kb_section` (usada na citação) e perde a poda de subárvore da
denylist — hoje uma página barrada impede a visita aos filhos; com busca plana
os filhos voltam sozinhos no resultado e entram. Enfraqueceria a defesa em
profundidade da regra nº 4 em troca de cobrir um caso (subpágina compartilhada
isoladamente, com o pai não compartilhado) que não corresponde ao modelo de
curadoria em uso.
```

- [x] **Step 2: Atualizar o índice do README de ADRs**

Em `docs/adr/README.md`, na tabela "Índice de ADRs": trocar o status do 0012 e do 0014 e acrescentar a linha do 0015.

```markdown
| [0011](0011-kb-restrita-root-notion.md) | Base de conhecimento restrita ao subtree de um root configurável do Notion | *substituído pelo 0015* |
| [0012](0012-escopo-kb-aplicado-na-recuperacao.md) | Escopo da KB aplicado também na recuperação, não só na descoberta | *parcialmente substituído pelo 0015* |
| [0013](0013-trace-por-turno-no-postgres.md) | Trace por turno persistido no Postgres, coletado num ponto único | Aceito |
| [0014](0014-kb-multi-root.md) | KB é a união dos subtrees de múltiplos roots do Notion | *substituído pelo 0015* |
| [0015](0015-kb-escopo-descoberto-pela-permissao.md) | Escopo da KB descoberto pela permissão do Notion | Aceito |
```

- [x] **Step 3: Conferir que os links do ADR resolvem**

Run: `ls docs/adr/0011-kb-restrita-root-notion.md docs/adr/0012-escopo-kb-aplicado-na-recuperacao.md docs/adr/0014-kb-multi-root.md docs/superpowers/specs/2026-08-11-mvp-lancamento-fase1-design.md`
Expected: os quatro caminhos existem (os links relativos do ADR apontam para eles).

- [x] **Step 4: Commit**

```bash
git add docs/adr/0015-kb-escopo-descoberto-pela-permissao.md docs/adr/README.md
git commit -m "docs(adr): ADR-0015 — escopo da KB vem da permissão do Notion"
```

---

### Task 2: Descoberta dos roots a partir do `search`

**Files:**
- Modify: `src/support/clients/notion/notion_client.py` (`list_approved_pages`, `list_workspace_root_pages`, remover `_require_roots`)
- Modify: `frontend/src/features/ops/architectureMap.ts:35` (descrição da caixa `notion-mcp`)
- Test: `tests/unit/support/clients/notion/test_notion_client_scope.py`

**Interfaces:**
- Consumes: `WorkspaceRootPage(id, title)` e `_collect_scope(call, root_id) -> list[NotionPage]`, ambos já existentes e inalterados.
- Produces: `NotionClient.list_approved_pages() -> list[NotionPage]` sem leitura de settings; `NotionClient._workspace_root_pages(call) -> list[WorkspaceRootPage]` (privado, recebe o `call` de uma sessão já aberta). `KnowledgeBaseConfigError` continua sendo a exceção de descoberta vazia.

- [x] **Step 1: Escrever os testes que falham**

Substituir os três últimos testes de `tests/unit/support/clients/notion/test_notion_client_scope.py` (os que hoje monkeypatcham `NOTION_KB_ROOT_PAGE_IDS`: `test_list_approved_pages_walks_every_root`, `test_page_reachable_from_two_roots_keeps_the_first_declared`, `test_list_approved_pages_raises_when_no_root_configured`) por estes. Os helpers `_child_page`, `_child_database`, `_paragraph` e `_fake_session` no topo do arquivo ficam como estão.

```python
def _make_discovery_call(tree: dict[str, list[dict]], roots: list[dict], requested: list[str]):
    """`call` que atende tanto a busca de roots quanto a travessia de blocos."""

    async def call(tool: str, args: dict):
        if tool == "API-post-search":
            return {"results": roots, "has_more": False}
        assert tool == "API-get-block-children"
        block_id = args["block_id"]
        requested.append(block_id)
        return {"results": tree.get(block_id, []), "has_more": False}

    return call


def _workspace_page(page_id: str, title: str) -> dict:
    return {
        "object": "page",
        "id": page_id,
        "parent": {"type": "workspace"},
        "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}},
    }


@pytest.mark.asyncio
async def test_roots_come_from_what_the_integration_sees(monkeypatch):
    # Nenhuma env var: o escopo é o que o search devolve no nível do workspace.
    tree = {
        "roota": [_child_page("A", "Programs")],
        "A": [],
        "rootb": [_child_page("B", "Código de Cultura")],
        "B": [],
    }
    roots = [_workspace_page("roota", "Products"), _workspace_page("rootb", "Código de Cultura")]
    requested: list[str] = []
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, requested)),
    )

    pages = await NotionClient().list_approved_pages()

    assert {p.id for p in pages} == {"A", "B"}
    assert {p.id: p.kb_root_page_id for p in pages} == {"A": "roota", "B": "rootb"}


@pytest.mark.asyncio
async def test_a_page_below_a_root_that_was_never_in_any_allowlist_is_discovered(monkeypatch):
    # Regressão do critério de aceite: página de um root que nunca esteve na
    # allowlist entra sem nenhuma mudança de configuração.
    tree = {"labs": [_child_page("L1", "Coding Labs — guia")], "L1": []}
    roots = [_workspace_page("labs", "Borderless Coding Labs")]
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, [])),
    )

    pages = await NotionClient().list_approved_pages()

    assert [p.id for p in pages] == ["L1"]
    assert pages[0].kb_root_page_id == "labs"


@pytest.mark.asyncio
async def test_page_reachable_from_two_roots_keeps_the_first_discovered(monkeypatch):
    tree = {
        "roota": [_child_page("SHARED", "Compartilhada")],
        "rootb": [_child_page("SHARED", "Compartilhada")],
        "SHARED": [],
    }
    roots = [_workspace_page("roota", "Products"), _workspace_page("rootb", "Cultura")]
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, [])),
    )

    pages = await NotionClient().list_approved_pages()

    assert len(pages) == 1
    assert pages[0].kb_root_page_id == "roota"


@pytest.mark.asyncio
async def test_empty_discovery_aborts_instead_of_wiping_the_base(monkeypatch):
    # Descoberta vazia = token revogado / MCP fora do ar. Reconciliar isso
    # soft-deletaria toda a base numa rodada — por isso aborta.
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call({}, [], [])),
    )

    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().list_approved_pages()
```

Remover também o import agora não usado de `settings` no topo do arquivo, se nenhum outro teste dele usar (`grep -n "settings" tests/unit/support/clients/notion/test_notion_client_scope.py`).

- [x] **Step 2: Rodar os testes e ver falhar pelo motivo certo**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v`
Expected: os quatro testes novos FALHAM. `test_roots_come_from_what_the_integration_sees` falha com `KnowledgeBaseConfigError` (`list_approved_pages` ainda lê a env var vazia), não com `AttributeError` ou erro de import — se falhar por outro motivo, o teste está errado, não o código.

- [x] **Step 3: Extrair `_workspace_root_pages` recebendo o `call`**

Em `src/support/clients/notion/notion_client.py`, dividir `list_workspace_root_pages` em duas: a pública abre a sessão, a privada recebe o `call`. Isso é o que permite à `list_approved_pages` descobrir os roots e percorrê-los numa sessão MCP só.

```python
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
            # `has_more=True` sem `next_cursor` deixaria `cursor` voltando a
            # `None` — args idênticos ao primeiro loop, `while True` nunca
            # sairia, e o SyncKnowledgeBaseJob penduraria segurando o advisory
            # lock. Sair também quando o cursor falta é o que evita isso.
            if not data.get("has_more") or not data.get("next_cursor"):
                return pages
            cursor = data.get("next_cursor")
```

- [x] **Step 4: Trocar a fonte dos roots em `list_approved_pages`**

Substituir **apenas o corpo** de `list_approved_pages`. **Não apague `_require_roots` nesta task** — `get_page_in_scope` e `_find_root` ainda o chamam, e removê-lo agora quebraria os dois. A Task 3 o apaga junto com o último chamador.

```python
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
                for page in await self._collect_scope(call, root.id):
                    key = normalize_page_id(page.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(page)
        return collected
```

- [x] **Step 5: Rodar os testes**

Run: `pytest tests/unit/support/clients/notion/ -v`
Expected: PASS — o diretório inteiro, inclusive `test_notion_client_ancestry.py`, que ainda exercita `_require_roots` e por isso não pode ser quebrado aqui. Os testes de `_collect_scope` (denylist, `child_database`, `section`) continuam verdes sem alteração: a travessia não mudou.

- [x] **Step 6: Atualizar a descrição da caixa no mapa de arquitetura**

Em `frontend/src/features/ops/architectureMap.ts`, na caixa `notion-mcp`:

```ts
        description: "Descobre as páginas de topo que a integração enxerga e lê o subtree de cada uma. O que não é compartilhado não é visitado.",
```

- [x] **Step 7: Rodar o teste do mapa**

Run: `cd frontend && npx vitest run src/features/ops/architectureMap.test.ts`
Expected: PASS (nenhum arquivo declarado no mapa mudou de caminho; só a descrição).

- [x] **Step 8: Commit**

```bash
git add src/support/clients/notion/notion_client.py tests/unit/support/clients/notion/test_notion_client_scope.py frontend/src/features/ops/architectureMap.ts
git commit -m "feat(kb): roots vêm do que a integração do Notion enxerga"
```

---

### Task 3: Ancestralidade vira derivação de procedência

**Files:**
- Modify: `src/support/clients/notion/notion_client.py` (`get_page_in_scope` → `get_page_with_provenance`, `_find_root` → `_find_top_level_page`)
- Test: `tests/unit/support/clients/notion/test_notion_client_ancestry.py`

**Interfaces:**
- Consumes: `NotionPage` (inalterada), `KnowledgeCurationPolicy.should_ingest`.
- Produces: `NotionClient.get_page_with_provenance(page_id: str) -> NotionPage` — **nunca devolve `None`**; `is_approved` carrega o veredito da curadoria e `kb_root_page_id` a página de topo de onde a página descende (ou `None`). `NotionClient._find_top_level_page(call, page_id) -> str | None`. As Tasks 4 e 6 consomem exatamente essa assinatura.

- [x] **Step 1: Reescrever o teste de ancestralidade**

Substituir `tests/unit/support/clients/notion/test_notion_client_ancestry.py` inteiro. O arquivo hoje testa `_find_root` contra uma allowlist; passa a testar a derivação de procedência, que não recusa nada.

```python
"""Procedência por ancestralidade: `_find_top_level_page` responde de qual página
de topo uma página descende, subindo a cadeia de `parent` (ADR-0015). Não
autoriza nada — quem recusa é a curadoria."""

import pytest

from src.support.clients.notion.notion_client import NotionClient


def _make_call(pages: dict[str, dict]):
    async def call(tool: str, args: dict):
        assert tool == "API-retrieve-a-page"
        return pages[args["page_id"]]

    return call


@pytest.mark.asyncio
async def test_climbs_to_the_top_level_page():
    pages = {
        "leaf": {"parent": {"type": "page_id", "page_id": "mid"}},
        "mid": {"parent": {"type": "page_id", "page_id": "rootB"}},
        "rootB": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "leaf") == "rootb"


@pytest.mark.asyncio
async def test_a_top_level_page_is_its_own_provenance():
    pages = {"rootA": {"parent": {"type": "workspace"}}}
    assert await NotionClient()._find_top_level_page(_make_call(pages), "rootA") == "roota"


@pytest.mark.asyncio
async def test_any_top_level_page_qualifies_now():
    # "growth" nunca esteve em allowlist nenhuma; ainda assim é procedência
    # válida — não existe mais lista contra a qual comparar.
    pages = {
        "sop": {"parent": {"type": "page_id", "page_id": "growth"}},
        "growth": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "sop") == "growth"


@pytest.mark.asyncio
async def test_database_row_has_no_top_level_page():
    # Linha de banco não descende de página de topo. Procedência `None` — a
    # recusa em si é da curadoria, não daqui.
    pages = {"row": {"parent": {"type": "data_source_id", "data_source_id": "ds1"}}}
    assert await NotionClient()._find_top_level_page(_make_call(pages), "row") is None


@pytest.mark.asyncio
async def test_cycle_does_not_hang():
    pages = {
        "a": {"parent": {"type": "page_id", "page_id": "b"}},
        "b": {"parent": {"type": "page_id", "page_id": "a"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "a") is None
```

- [x] **Step 2: Rodar e ver falhar**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_ancestry.py -v`
Expected: FAIL — `AttributeError: 'NotionClient' object has no attribute '_find_top_level_page'`.

- [x] **Step 3: Trocar `_find_root` por `_find_top_level_page`**

Em `src/support/clients/notion/notion_client.py`, substituir o método `_find_root` inteiro por:

```python
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
```

- [x] **Step 4: Trocar `get_page_in_scope` por `get_page_with_provenance`**

Substituir o método `get_page_in_scope` inteiro por:

```python
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
```

- [x] **Step 5: Rodar os testes**

Run: `pytest tests/unit/support/clients/notion/test_notion_client_ancestry.py -v`
Expected: PASS (5 testes).

- [x] **Step 5b: Apagar `_require_roots`**

Agora que `get_page_in_scope` e `_find_root` — seus dois últimos chamadores — deixaram de existir, apagar o método `_require_roots` inteiro de `notion_client.py`. A Task 2 deliberadamente o deixou de pé para não quebrar esses dois.

Run: `grep -n "_require_roots" src/support/clients/notion/notion_client.py`
Expected: nenhuma linha.

- [x] **Step 6: Renomear as duas chamadas, sem mudar comportamento**

O método mudou de nome; os dois chamadores precisam acompanhar **nesta task**, senão o commit fica vermelho até a Task 4. É rename puro — a checagem de `is_approved` é da Task 4, não daqui.

Em `src/support/agent/tools.py`, dentro de `FetchNotionTool.run`, trocar só a chamada:

```python
        page = await self._notion.get_page_with_provenance(page_id)
```

Em `src/app/console/commands/knowledge_ingest_command.py`, dentro de `handle`, o mesmo:

```python
        page = await self._notion.get_page_with_provenance(page_id)
```

Nos fakes dos testes desses dois arquivos (`tests/unit/support/agent/test_tools_scope.py` e `tests/unit/app/console/test_knowledge_ingest_command.py`), renomear o método `get_page_in_scope` para `get_page_with_provenance`. **Não mexa nas asserções** — os fakes que devolvem `None` continuam devolvendo `None`, e o `if page is None` dos chamadores continua funcionando. A Task 4 reescreve esses dois arquivos por inteiro.

- [x] **Step 7: Rodar a suíte de unit inteira**

Run: `pytest tests/unit -q`
Expected: PASS. Nenhum commit deste plano pode deixar a suíte vermelha — se falhar aqui, o rename ficou incompleto.

- [x] **Step 8: Confirmar que o nome antigo sumiu**

Run: `grep -rn "get_page_in_scope\|_find_root\b" src/ tests/ --include=*.py | grep -v __pycache__`
Expected: nenhuma linha.

- [x] **Step 9: Commit**

```bash
git add src/support/clients/notion/notion_client.py src/support/agent/tools.py src/app/console/commands/knowledge_ingest_command.py tests/unit/
git commit -m "refactor(kb): ancestralidade deriva procedência, não autoriza"
```

---

### Task 4: A curadoria assume a recusa na leitura por id

Esta é a task crítica de segurança do plano: sem ela, a Task 3 deixa o agente capaz de buscar linha de banco (PII) por id.

**Files:**
- Modify: `src/support/agent/tools.py` (`FetchNotionTool.run`)
- Modify: `src/app/console/commands/knowledge_ingest_command.py` (`handle`)
- Test: `tests/unit/support/agent/test_tools_scope.py`
- Test: `tests/unit/app/console/test_knowledge_ingest_command.py`

**Interfaces:**
- Consumes: `NotionClient.get_page_with_provenance(page_id) -> NotionPage` (Task 3).
- Produces: nenhuma assinatura nova. A mensagem de recusa da tool continua contendo a substring `"fora do escopo"`, da qual os testes dependem.

- [x] **Step 1: Reescrever o teste da tool**

Substituir `tests/unit/support/agent/test_tools_scope.py` inteiro:

```python
"""`fetch_notion_page` não pode furar a curadoria (ADR-0015): página que a
`KnowledgeCurationPolicy` reprova — linha de banco (PII), título na denylist —
não vira contexto de resposta, mesmo sendo legível pela integração."""

import pytest

from src.support.agent.tools import FetchNotionTool
from src.support.clients.notion.notion_client import NotionPage


class _FakeNotion:
    """Client falso: registra o que foi pedido e simula o veredito da curadoria."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.fetched: list[str] = []

    async def get_page_with_provenance(self, page_id: str) -> NotionPage:
        self.fetched.append(page_id)
        return NotionPage(
            id=page_id,
            title="Bootcamp Web3",
            content="conteúdo da página",
            url="https://notion.so/p",
            is_approved=self._approved,
            kb_root_page_id="products",
        )


@pytest.mark.asyncio
async def test_approved_page_is_returned_as_tool_content():
    notion = _FakeNotion(approved=True)
    out = await FetchNotionTool(notion=notion).run("pagina-de-products")

    assert out.startswith("<<TOOL_CONTENT>>")
    assert "conteúdo da página" in out
    assert notion.fetched == ["pagina-de-products"]


@pytest.mark.asyncio
async def test_content_rejected_by_curation_never_reaches_the_model():
    # Regressão da Task 3: sem esta checagem, tirar a ancestralidade deixaria
    # linha de banco (PII) entrar direto no contexto da resposta.
    notion = _FakeNotion(approved=False)
    out = await FetchNotionTool(notion=notion).run("linha-de-tracker")

    assert "conteúdo da página" not in out
    assert "fora do escopo" in out.lower()
```

- [x] **Step 2: Rodar e ver falhar**

Run: `pytest tests/unit/support/agent/test_tools_scope.py -v`
Expected: FAIL em `test_content_rejected_by_curation_never_reaches_the_model` — a tool devolve o conteúdo da página reprovada, porque ainda não checa `is_approved`. O outro teste passa. Se o primeiro também falhar, o rename da Task 3 ficou incompleto.

- [x] **Step 3: Trocar a checagem na tool**

Em `src/support/agent/tools.py`, substituir a docstring da classe e o método `run`:

```python
class FetchNotionTool:
    """Busca uma página do Notion por id — **filtrada pela curadoria** (ADR-0015).

    O id chega do modelo (via citação ou inferência), não da travessia de
    descoberta. O escopo em si é a permissão da integração, que o MCP já aplica;
    o que precisa ser checado aqui é o veredito da `KnowledgeCurationPolicy`,
    que barra linha de banco (tracker/PII) e títulos da denylist.
    """

    def __init__(self, notion: NotionClient) -> None:
        self._notion = notion

    async def run(self, page_id: str) -> str:
        page = await self._notion.get_page_with_provenance(page_id)
        if not page.is_approved:
            return wrap_tool_content(
                "(página fora do escopo da base de conhecimento — não disponível)"
            )
        return wrap_tool_content(f"[{page.title} — {page.url}]\n{page.content}")
```

- [x] **Step 4: Rodar o teste da tool**

Run: `pytest tests/unit/support/agent/test_tools_scope.py -v`
Expected: PASS (2 testes).

- [x] **Step 5: Reescrever o teste do comando de ingestão**

Substituir os dois primeiros blocos de `tests/unit/app/console/test_knowledge_ingest_command.py` — o docstring do módulo, a classe `_FakeNotionOutOfScope` e o teste `test_refuses_an_out_of_scope_page_and_does_not_persist` — por:

```python
"""`knowledge:ingest` não pode furar a curadoria (ADR-0015): um id avulso
digitado/colado não passou pela travessia de descoberta, então pode ser qualquer
página que a integração alcance — inclusive linha de banco (tracker/PII)."""

import pytest

from src.app.console.commands.knowledge_ingest_command import KnowledgeIngestCommand
from src.support.clients.notion.notion_client import NotionPage
from src.support.core.exceptions import ValidationError


class _FakeNotionRejected:
    """Simula o veredito da curadoria: página reprovada (ex.: linha de banco)."""

    def __init__(self) -> None:
        self.checked: list[str] = []

    async def get_page_with_provenance(self, page_id: str) -> NotionPage:
        self.checked.append(page_id)
        return NotionPage(
            id=page_id, title="Onboarding Control", content="PII", url="https://n",
            is_approved=False, last_edited_time=None, kb_root_page_id=None,
        )


@pytest.mark.asyncio
async def test_refuses_a_page_rejected_by_curation_and_does_not_persist(monkeypatch):
    notion = _FakeNotionRejected()
    command = KnowledgeIngestCommand(notion=notion)
    command.input = {"page_id": "linha-de-tracker"}

    # Sentinela: se o comando chegar a abrir sessão de banco, o teste teria que
    # ter DB disponível. Ele NÃO deve chegar lá — falhar antes é o ponto.
    def _boom():
        raise AssertionError("não deveria abrir sessão para página reprovada")

    monkeypatch.setattr(
        "src.app.console.commands.knowledge_ingest_command.AsyncSessionLocal", _boom
    )

    with pytest.raises(ValidationError, match="curadoria"):
        await command.handle()

    assert notion.checked == ["linha-de-tracker"]
```

No segundo teste (`test_persists_the_root_that_contains_the_page`), trocar o docstring e renomear o método da classe `_FakeNotionInScope`, mantendo todo o resto (fakes de ingest e de sessão) intacto:

```python
@pytest.mark.asyncio
async def test_persists_the_top_level_page_that_contains_the_page(monkeypatch):
    """A procedência vem da página de topo de onde ela descende — resolvida por
    `get_page_with_provenance`, que subiu a cadeia de `parent`."""

    class _FakeNotionInScope:
        async def get_page_with_provenance(self, page_id: str):
            return NotionPage(
                id=page_id, title="Página", content="corpo", url="https://n",
                is_approved=True, last_edited_time=None, kb_root_page_id="rootb",
            )
```

- [x] **Step 6: Rodar e ver falhar**

Run: `pytest tests/unit/app/console/test_knowledge_ingest_command.py -v`
Expected: FAIL em `test_refuses_a_page_rejected_by_curation_and_does_not_persist` — o comando ainda recusa só quando a página é `None`, e o fake novo devolve uma `NotionPage` reprovada. O comando segue em frente e a sentinela `_boom` dispara.

- [x] **Step 7: Trocar a checagem no comando**

Em `src/app/console/commands/knowledge_ingest_command.py`, substituir o bloco de checagem no início de `handle` (o comentário longo + a chamada + o `raise`) por:

```python
        # Checa a curadoria ANTES de abrir sessão: um id avulso (digitado ou
        # colado) não passou pela travessia de descoberta, então pode ser
        # qualquer página que a integração alcance — inclusive linha de banco
        # (tracker/PII). O escopo em si é a permissão da integração (ADR-0015);
        # o que falta checar aqui é o veredito da KnowledgeCurationPolicy.
        page = await self._notion.get_page_with_provenance(page_id)
        if not page.is_approved:
            raise ValidationError(
                f"Página {page_id} foi reprovada pela curadoria (linha de banco "
                "ou título na denylist) — ingestão abortada."
            )
```

E, no bloco de sessão, ajustar o comentário da procedência:

```python
                # A procedência vem da página de topo de onde ela descende
                # (resolvida por `get_page_with_provenance`), não de env var.
                root_page_id = page.kb_root_page_id or ""
```

- [x] **Step 8: Rodar os dois arquivos de teste**

Run: `pytest tests/unit/support/agent/test_tools_scope.py tests/unit/app/console/test_knowledge_ingest_command.py -v`
Expected: PASS.

- [x] **Step 9: Confirmar que a curadoria é checada nos dois caminhos**

Run: `grep -rn "is_approved" src/support/agent/tools.py src/app/console/commands/knowledge_ingest_command.py`
Expected: uma linha em cada arquivo. É a garantia que substitui a recusa por ancestralidade — sem ela, linha de banco (PII) entra no contexto.

- [x] **Step 10: Commit**

```bash
git add src/support/agent/tools.py src/app/console/commands/knowledge_ingest_command.py tests/unit/support/agent/test_tools_scope.py tests/unit/app/console/test_knowledge_ingest_command.py
git commit -m "fix(kb): curadoria barra linha de banco na leitura por id"
```

---

### Task 5: A recuperação perde o filtro por root

**Files:**
- Modify: `src/domain/documents/repositories/document_repository.py` (`list_sections`, `count_active`, `count_archived`; remover import de `settings`; acrescentar `count_by_root`)
- Modify: `src/domain/documents/repositories/document_chunk_repository.py` (`search_similar`, `nearest_distance`, `count_in_scope`)
- Modify: `frontend/src/features/ops/architectureMap.ts:108` (descrição da caixa `retrieval`)
- Test: `tests/integration/domain/documents/test_chunk_repository_scope_filter.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `DocumentRepository.count_by_root() -> dict[str, int]` — chaves são `kb_root_page_id` (string vazia para documentos sem procedência), valores são contagens de documentos aprovados e não removidos. A Task 6 consome exatamente isso.

- [x] **Step 1: Reescrever o teste de integração do filtro**

Substituir `tests/integration/domain/documents/test_chunk_repository_scope_filter.py` inteiro. O fixture `seed_document_with_chunk(title, kb_root_page_id, kb_section, embedding, soft_deleted)` já existe em `tests/integration/conftest.py` e não muda.

```python
"""Recuperação sem filtro de procedência (ADR-0015): o escopo é a permissão do
Notion, aplicada na descoberta e na reconciliação — não uma comparação de
`kb_root_page_id` no SQL de leitura. O que sobrevive aqui é `deleted_at`."""

import pytest

from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)

UM_ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"

# Vetor NÃO-nulo: cosine_distance contra vetor zero é indefinida (NaN no pgvector)
# e tornaria a ordenação — e o limiar — imprevisíveis.
_QUERY = [1.0] + [0.0] * 1535


@pytest.mark.asyncio
async def test_provenance_no_longer_filters_retrieval(seed_document_with_chunk):
    await seed_document_with_chunk(title="De um root", kb_root_page_id=UM_ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert {"De um root", "De outro root"} <= {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_document_without_provenance_is_retrievable(seed_document_with_chunk):
    # Antes: `IN (roots)` excluía NULL, e sem roots a guarda fail-closed
    # devolvia [] para tudo. Sem filtro, o documento entra normalmente.
    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert "Sem procedência" in {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_soft_deleted_document_is_still_excluded(seed_document_with_chunk):
    # A garantia que SOBREVIVE: a reconciliação do sync continua sendo o que
    # tira documento de circulação.
    await seed_document_with_chunk(
        title="Despublicada", kb_root_page_id=UM_ROOT, soft_deleted=True
    )

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert "Despublicada" not in {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_nearest_distance_ignores_provenance_too(seed_document_with_chunk):
    # `nearest_distance` serve o trace do caminho de recusa e tinha a mesma
    # guarda fail-closed: sem roots, devolvia None.
    await seed_document_with_chunk(title="Qualquer", kb_root_page_id=OUTRO_ROOT)

    assert await DocumentChunkRepository().nearest_distance(_QUERY) is not None
```

- [x] **Step 2: Rodar e ver falhar**

Run: `pytest tests/integration/domain/documents/test_chunk_repository_scope_filter.py -v`
Expected: FAIL — sem `NOTION_KB_ROOT_PAGE_IDS` no ambiente de teste, `search_similar` cai na guarda `if not roots: return []` e devolve lista vazia. Se o banco não estiver de pé: `docker compose -f docker/docker-compose.yml up -d` com `DB_PORT=5434`.

- [x] **Step 3: Tirar o filtro das três consultas do `DocumentChunkRepository`**

Em `src/domain/documents/repositories/document_chunk_repository.py`, nos métodos `search_similar`, `nearest_distance` e `count_in_scope`: apagar as linhas `roots = settings.kb_root_page_ids`, o bloco `if not roots: ...` (com o comentário longo da guarda) e o predicado `DocumentModel.kb_root_page_id.in_(roots)` de cada `where`. Manter `status == "approved"`, `deleted_at.is_(None)` e o corte por distância. **Manter** o import de `settings` — `RAG_TOP_K` e `RAG_MAX_DISTANCE` continuam vindo dele.

Renomear `count_in_scope` não é necessário; ajustar sua docstring é:

```python
    async def count_in_scope(self) -> int:
        """Chunks de documentos ativos e aprovados — quanto o oráculo tem para servir.

        Mesmo filtro do `search_similar`, sem o corte por distância. Desde o
        ADR-0015 não há filtro por procedência: o escopo é o que a integração
        do Notion enxerga, aplicado na descoberta e na reconciliação.
        """
```

- [x] **Step 4: Tirar o filtro das três consultas do `DocumentRepository`**

Em `src/domain/documents/repositories/document_repository.py`, o mesmo em `list_sections`, `count_active` e `count_archived`. Aqui o import `from src.support.core.settings import settings` fica **sem uso** — remova-o. Ajustar as docstrings, que hoje falam em "conjunto de roots vigente":

```python
    async def list_sections(self) -> list[str]:
        """Seções distintas dos documentos ativos, ordenadas."""
```

```python
    async def count_active(self) -> int:
        """Documentos aprovados e não removidos — exatamente o que o oráculo serve."""
```

```python
    async def count_archived(self) -> int:
        """Documentos removidos por soft-delete na reconciliação do sync."""
```

- [x] **Step 5: Acrescentar `count_by_root`**

No mesmo arquivo, depois de `count_archived`:

```python
    async def count_by_root(self) -> dict[str, int]:
        """Documentos ativos agrupados por procedência (`kb_root_page_id`).

        Diagnóstico, não escopo (ADR-0015): responde "o oráculo está mesmo
        lendo o que eu liberei?" no `knowledge:roots`. Documento sem
        procedência gravada entra sob a chave vazia.
        """
        result = await self.session.execute(
            select(DocumentModel.kb_root_page_id, func.count())
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
            )
            .group_by(DocumentModel.kb_root_page_id)
        )
        return {(root or ""): count for root, count in result.all()}
```

- [x] **Step 6: Verificar que `settings` sumiu do repositório de documentos**

Run: `grep -n "settings" src/domain/documents/repositories/document_repository.py`
Expected: nenhuma linha.

- [x] **Step 7: Rodar os testes**

Run: `pytest tests/integration/domain/documents/ tests/unit/domain/documents/ -v`
Expected: PASS. Testes que monkeypatcham `NOTION_KB_ROOT_PAGE_IDS` e ainda passarem, passam por inércia — o `monkeypatch` vira inócuo; remova esses `monkeypatch` onde encontrá-los.

- [x] **Step 8: Atualizar a descrição da caixa de retrieval no mapa**

Em `frontend/src/features/ops/architectureMap.ts`, na caixa `retrieval`:

```ts
        description: "Top-k no pgvector sobre os documentos ativos, cortado pela distância máxima.",
```

- [x] **Step 9: Commit**

```bash
git add src/domain/documents/repositories/ tests/integration/domain/documents/test_chunk_repository_scope_filter.py frontend/src/features/ops/architectureMap.ts
git commit -m "feat(kb): recuperação deixa de filtrar por procedência"
```

---

### Task 6: Comandos, job e seed — o conceito de drift some

**Files:**
- Delete: `src/domain/documents/actions/detect_kb_root_drift_action.py`
- Delete: `src/domain/documents/dtos/kb_root_drift.py`
- Delete: `tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py`
- Modify: `src/domain/documents/actions/__init__.py`
- Modify: `src/app/console/jobs/sync_knowledge_base_job.py` (remover `_warn_on_drift`)
- Modify: `src/app/console/commands/knowledge_roots_command.py` (reescrever)
- Modify: `src/app/console/commands/knowledge_calibrate_command.py:53,76`
- Modify: `src/domain/documents/actions/sync_knowledge_base_action.py` (comentário de `left_scope`)
- Modify: `database/seeds/dev_documents_seed.py:37`
- Test: `tests/unit/app/console/test_knowledge_roots_command.py` (criar se não existir)

**Interfaces:**
- Consumes: `DocumentRepository.count_by_root() -> dict[str, int]` (Task 5); `NotionClient.list_workspace_root_pages() -> list[WorkspaceRootPage]` (Task 2).
- Produces: nenhuma assinatura consumida por tasks posteriores. Depois desta task, o único leitor restante de `settings.kb_root_page_ids` deve ser zero — é o que destrava a Task 7.

- [x] **Step 1: Escrever o teste do comando novo**

Criar (ou substituir) `tests/unit/app/console/test_knowledge_roots_command.py`:

```python
"""`knowledge:roots` deixou de reportar drift (ADR-0015): allowlist e
visibilidade viraram a mesma coisa. Ele agora responde "o oráculo está lendo o
que eu liberei?" — roots em consumo e quantos documentos vieram de cada um."""

import pytest

from src.app.console.commands.knowledge_roots_command import KnowledgeRootsCommand
from src.support.clients.notion.notion_client import WorkspaceRootPage


class _FakeNotion:
    async def list_workspace_root_pages(self):
        return [
            WorkspaceRootPage(id="products", title="Products"),
            WorkspaceRootPage(id="labs", title="Borderless Coding Labs"),
        ]


class _FakeDocuments:
    async def count_by_root(self):
        return {"products": 42}


@pytest.mark.asyncio
async def test_lists_roots_with_document_counts(capsys):
    await KnowledgeRootsCommand(notion=_FakeNotion(), documents=_FakeDocuments()).handle()

    out = capsys.readouterr().out
    assert "Products" in out and "42" in out
    # Root visível sem documento ingerido: sync ainda não rodou, ou tudo abaixo
    # dele foi barrado pela curadoria. Precisa aparecer, com zero.
    assert "Borderless Coding Labs" in out
    assert "0" in out


@pytest.mark.asyncio
async def test_reports_when_the_integration_sees_nothing(capsys):
    class _Empty:
        async def list_workspace_root_pages(self):
            return []

    await KnowledgeRootsCommand(notion=_Empty(), documents=_FakeDocuments()).handle()

    assert "nenhuma página" in capsys.readouterr().out.lower()
```

- [x] **Step 2: Rodar e ver falhar**

Run: `pytest tests/unit/app/console/test_knowledge_roots_command.py -v`
Expected: FAIL — `TypeError`, porque o `__init__` atual aceita `action`, não `notion`/`documents`.

- [x] **Step 3: Reescrever o comando**

Substituir `src/app/console/commands/knowledge_roots_command.py` inteiro:

```python
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal


class KnowledgeRootsCommand(Command):
    signature = "knowledge:roots"
    description = (
        "Lista as páginas de topo que a integração do Notion enxerga — o escopo "
        "da KB — com a contagem de documentos ingeridos sob cada uma."
    )

    def __init__(self, notion=None, documents=None) -> None:
        super().__init__()
        # Injetáveis em teste; o autodiscovery do kernel instancia sem argumentos.
        self._notion = notion or NotionClient()
        self._documents = documents

    async def handle(self) -> None:
        roots = await self._notion.list_workspace_root_pages()
        if not roots:
            print(
                "A integração não enxerga nenhuma página de nível de workspace.\n"
                "Token revogado, MCP fora do ar, ou nada compartilhado — o sync "
                "abortaria neste estado."
            )
            return

        counts = await self._counts()
        print(f"Roots em consumo: {len(roots)}\n")
        for root in roots:
            print(f"  {counts.get(root.id, 0):>5} doc(s)  {root.title}  [{root.id}]")

        orphans = {k: v for k, v in counts.items() if k not in {r.id for r in roots}}
        if orphans:
            # Documento cuja procedência não está mais entre os roots visíveis:
            # página despublicada desde o último sync. Some no sync seguinte.
            print("\nDocumentos de procedência não mais visível (saem no próximo sync):")
            for root_id, count in orphans.items():
                print(f"  {count:>5} doc(s)  [{root_id or '(sem procedência)'}]")

    async def _counts(self) -> dict[str, int]:
        if self._documents is not None:
            return await self._documents.count_by_root()
        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                return await DocumentRepository().count_by_root()
            finally:
                CurrentAsyncSessionContext.clear()
```

- [x] **Step 4: Rodar o teste do comando**

Run: `pytest tests/unit/app/console/test_knowledge_roots_command.py -v`
Expected: PASS (2 testes).

- [x] **Step 5: Apagar a Action de drift, o DTO e o teste dela**

```bash
git rm src/domain/documents/actions/detect_kb_root_drift_action.py \
       src/domain/documents/dtos/kb_root_drift.py \
       tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py
```

Este é um dos dois casos autorizados de teste deletado sem substituto: o objeto testado deixou de existir, e o que ele garantia (visibilidade de divergência entre duas listas) não tem mais sentido com uma lista só.

Em `src/domain/documents/actions/__init__.py`, remover o import e a entrada de `DetectKbRootDriftAction` do `__all__`:

```python
from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction

__all__ = [
    "IngestDocumentAction",
    "ListKnowledgeSectionsAction",
    "SearchKnowledgeBaseAction",
]
```

- [x] **Step 6: Tirar o aviso de drift do job**

Em `src/app/console/jobs/sync_knowledge_base_job.py`, remover o import de `DetectKbRootDriftAction`, a chamada `await self._warn_on_drift(...)` e o método `_warn_on_drift` inteiro. O arquivo fica:

```python
import logging

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
```

- [x] **Step 7: Tirar o filtro do `knowledge:calibrate`**

Em `src/app/console/commands/knowledge_calibrate_command.py`: remover o bloco

```python
        if not settings.kb_root_page_ids:
            print("NOTION_KB_ROOT_PAGE_IDS não configurado — nada a calibrar.")
            return
```

e o predicado `DocumentModel.kb_root_page_id.in_(settings.kb_root_page_ids),` do `where`. O import de `settings` fica: `RAG_MAX_DISTANCE` continua sendo lido.

- [x] **Step 8: Trocar a procedência do seed de dev**

Em `database/seeds/dev_documents_seed.py`, substituir o comentário e o valor:

```python
                # Procedência de dev: constante estável, sem fingir uma página do
                # Notion. Desde o ADR-0015 a procedência não afeta recuperação —
                # ela é só diagnóstico.
                kb_root_page_id="seed",
```

Se `settings` ficar sem uso no arquivo, remova o import (`grep -n "settings" database/seeds/dev_documents_seed.py`).

- [x] **Step 9: Atualizar o comentário de `left_scope` no sync**

Em `src/domain/documents/actions/sync_knowledge_base_action.py`, o comentário longo acima de `left_scope` cita `settings.kb_root_page_ids` e "allowlist". Substituir por:

```python
                # Único motivo de saída de escopo observável aqui: a página não
                # apareceu em nenhuma travessia desta rodada. Um root que o Yuri
                # despublicou não é mais descoberto por `list_approved_pages`,
                # então suas páginas somem de `approved_ids` por AUSÊNCIA da
                # travessia — não porque comparamos a procedência gravada contra
                # uma lista. Essa segunda comparação já existiu aqui e era sempre
                # inalcançável; não reintroduza. Descoberta vazia não chega até
                # aqui: `list_approved_pages` aborta antes (ADR-0015).
```

- [x] **Step 10: Limpar o resíduo de allowlist no teste do sync**

`tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py` usa um
`FakeNotion`, então nunca leu a env var de verdade — a fixture abaixo é resíduo e
passa a mentir sobre o mecanismo. Remover a fixture `_roots` inteira e o import
`from src.support.core.settings import settings` do topo:

```python
@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)
```

E renomear o último teste, com o comentário atualizado (o comportamento não muda
— o que muda é o motivo pelo qual o root sumiu):

```python
@pytest.mark.asyncio
async def test_soft_deletes_documents_whose_root_is_no_longer_shared():
    # Um root que o Yuri despublicou deixa de ser descoberto por
    # `list_approved_pages` — a página some por AUSÊNCIA da travessia, não por
    # comparação de procedência. O NotionClient real não tem como devolver uma
    # página aprovada etiquetada com um root que ele não está percorrendo
    # (`_collect_scope` só etiqueta com os roots descobertos), então este é o
    # único cenário de saída de escopo que a action precisa (e consegue)
    # detectar.
    docs = FakeDocRepo([_existing("z", _dt(5), kb_root_page_id="rootremovido")])
```

- [x] **Step 11: Confirmar que não sobrou leitor da propriedade**

Run: `grep -rn "kb_root_page_ids" src/ database/ evals/ tests/ --include=*.py | grep -v __pycache__`
Expected: **nenhuma linha** fora de `src/support/core/settings.py` (a definição, que a Task 7 remove). Se sobrar alguma, conserte antes de commitar — a Task 7 quebra o import.

- [x] **Step 12: Rodar a suíte de unit**

Run: `pytest tests/unit -q`
Expected: PASS.

- [x] **Step 13: Commit**

```bash
git add -A src/domain/documents/actions/ src/domain/documents/dtos/ src/app/console/ database/seeds/dev_documents_seed.py tests/unit/
git commit -m "refactor(kb): drift some — knowledge:roots vira relatório de consumo"
```

---

### Task 7: Env vars viram detector de deploy defasado

**Files:**
- Modify: `src/support/core/settings.py` (remover a propriedade `kb_root_page_ids`, reescrever os comentários dos dois campos)
- Modify: `src/support/core/lifespan.py` (`_validate_kb_root_env`)
- Modify: `.env.example`
- Delete: `tests/unit/support/core/test_settings_kb_root.py`
- Test: `tests/unit/support/core/test_lifespan.py`

**Interfaces:**
- Consumes: nada (a Task 6 removeu o último leitor).
- Produces: nenhuma. `Settings.NOTION_KB_ROOT_PAGE_IDS` e `NOTION_KB_ROOT_PAGE_ID` permanecem como `str | None` crus, lidos só pelo detector.

- [x] **Step 1: Reescrever o teste do detector**

Substituir `tests/unit/support/core/test_lifespan.py` inteiro:

```python
import pytest

from src.support.core.lifespan import LifespanManager
from src.support.core.settings import settings


def test_raises_when_the_plural_root_env_var_is_still_set(monkeypatch):
    # Deploy defasado: o escopo agora vem da permissão da integração
    # (ADR-0015). Uma env var de root sobrando significa que alguém acha que
    # ainda controla o escopo por configuração — falhar alto é melhor que
    # deixar a crença passar silenciosa.
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    with pytest.raises(RuntimeError, match="ADR-0015"):
        LifespanManager._validate_kb_root_env()


def test_raises_when_the_old_singular_env_var_is_still_set(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", "abc123", raising=False)

    with pytest.raises(RuntimeError, match="ADR-0015"):
        LifespanManager._validate_kb_root_env()


def test_does_not_raise_when_neither_is_set(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta


def test_blank_value_is_not_treated_as_set(monkeypatch):
    # `NOTION_KB_ROOT_PAGE_IDS=` no .env chega como string vazia, não None.
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "   ", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta
```

- [x] **Step 2: Rodar e ver falhar**

Run: `pytest tests/unit/support/core/test_lifespan.py -v`
Expected: FAIL nos dois primeiros — o detector atual só levanta quando o nome antigo está setado **e** o novo está vazio, e a mensagem cita ADR-0014.

- [x] **Step 3: Reescrever o detector**

Em `src/support/core/lifespan.py`, substituir `_validate_kb_root_env` inteiro:

```python
    @staticmethod
    def _validate_kb_root_env() -> None:
        """Detecta deploy que ainda acha que controla o escopo da KB por env var.

        Desde o ADR-0015 o escopo é o que a integração do Notion enxerga —
        nenhum código lê essas variáveis para decidir escopo. Um deploy que
        ainda as exporta subiria normal, e a pessoa que as configurou acharia
        que restringiu a base quando não restringiu nada. Falhar no boot é
        melhor que essa crença silenciosa.
        """
        stale = [
            name
            for name in ("NOTION_KB_ROOT_PAGE_IDS", "NOTION_KB_ROOT_PAGE_ID")
            if (getattr(settings, name, None) or "").strip()
        ]
        if stale:
            raise RuntimeError(
                f"{', '.join(stale)} está definido, mas o escopo da base de "
                "conhecimento deixou de vir de variável de ambiente: agora é o "
                "que a integração do Notion enxerga (ADR-0015). Remova a "
                "variável do ambiente; para mudar o escopo, mude o "
                "compartilhamento no Notion."
            )
```

- [x] **Step 4: Remover a propriedade das settings**

Em `src/support/core/settings.py`, apagar a propriedade `kb_root_page_ids` inteira (incluindo o decorator `@property` e a docstring) e substituir o bloco de comentários dos dois campos por:

```python
    # --- Escopo da KB: NÃO se configura mais aqui ---
    # Desde o ADR-0015 o escopo é a união dos subtrees das páginas de nível de
    # workspace que a integração do Notion enxerga, descobertas a cada sync.
    # Estes dois campos sobrevivem SÓ como detectores: o `LifespanManager`
    # derruba o boot se qualquer um estiver preenchido, para que um deploy
    # defasado não suba achando que restringiu a base.
    NOTION_KB_ROOT_PAGE_IDS: str | None = None
    NOTION_KB_ROOT_PAGE_ID: str | None = None
```

Se `normalize_page_id` ficar sem uso no arquivo, remova o import (`grep -n "normalize_page_id" src/support/core/settings.py`).

- [x] **Step 5: Apagar o teste da propriedade**

```bash
git rm tests/unit/support/core/test_settings_kb_root.py
```

Segundo e último caso autorizado de teste deletado sem substituto: a propriedade que ele exercitava não existe mais, e o comportamento que sobra (detector) está coberto pelo `test_lifespan.py`.

- [x] **Step 6: Atualizar o `.env.example`**

Substituir o bloco de roots por:

```
# Escopo da KB: NÃO se configura aqui (ADR-0015). A base é o que a integração
# do Notion enxerga — para incluir ou excluir conteúdo, mude o compartilhamento
# no Notion. `python cli.py knowledge:roots` mostra o que está em consumo.
# NOTION_KB_ROOT_PAGE_IDS e NOTION_KB_ROOT_PAGE_ID derrubam o boot se definidas.
```

- [x] **Step 7: Tirar as variáveis do `.env` local**

Run: `grep -n "NOTION_KB_ROOT" .env`
Se aparecer, comente ou remova as linhas — senão a aplicação não sobe localmente.

- [x] **Step 8: Rodar os testes e o boot**

Run: `pytest tests/unit/support/core/ -v && python -c "from main import app; print('OK')"`
Expected: PASS e `OK`.

- [x] **Step 9: Commit**

```bash
git add -A src/support/core/settings.py src/support/core/lifespan.py .env.example tests/unit/support/core/
git commit -m "feat(kb): env var de root vira detector de deploy defasado"
```

---

### Task 8: Verificação de ponta a ponta e runbook de corte

**Files:**
- Modify: `docs/superpowers/plans/2026-08-31-kb-escopo-descoberto.md` (marcar as caixas concluídas)
- Nenhum arquivo de produção novo. Esta task é o portão: nada é dado como pronto sem o comando rodado e a saída lida.

**Interfaces:**
- Consumes: tudo das Tasks 1–7.
- Produces: nada.

- [x] **Step 1: Suíte completa**

Run: `pytest -q`
Expected: PASS, zero falhas, zero erros de coleta. Falha de coleta por import quebrado é o sintoma típico de Task 7 rodada fora de ordem.

- [x] **Step 2: Lint**

Run: `prospector`
Expected: sem achados novos. Import não usado (`settings`, `normalize_page_id`) é o achado esperado se algum passo de limpeza foi pulado.

- [x] **Step 3: Migrations intactas**

Run: `alembic check`
Expected: limpo, sem revisão pendente. Este plano não tem migration; qualquer diferença aqui é efeito colateral e precisa ser investigado, não commitado.

- [x] **Step 4: Frontend**

Run: `cd frontend && npm run build && npx vitest run`
Expected: build passa e testes verdes, incluindo `architectureMap.test.ts`.

- [x] **Step 5: Grep final das garantias removidas**

Run: `grep -rn "kb_root_page_ids\|get_page_in_scope\|DetectKbRootDrift\|_find_root\b" src/ database/ tests/ frontend/src --include=*.py --include=*.ts | grep -v __pycache__`
Expected: nenhuma linha. Qualquer sobra é código morto que ainda promete a garantia antiga.

- [ ] **Step 6: Corte em produção**

Não é passo de CI — é o runbook do deploy, executado por uma pessoa, nesta ordem:

```bash
# 1. Remover as env vars de root do ambiente de produção (senão o boot falha).
# 2. Deploy.
# 3. Imediatamente após o deploy subir:
python cli.py knowledge:sync
# 4. Conferir o que passou a ser consumido:
python cli.py knowledge:roots
```

O sync incremental (sem `--force`) já basta: página nunca vista entra por `current is None`, documento soft-deletado que volta ao escopo entra por `deleted_at`, página que trocou de root entra pela auto-cura de divergência de procedência, e a reconciliação de saída de escopo roda em qualquer sync não parcial, independente de `--force`. Usar `--force` aqui reingeriria a base inteira, inclusive as páginas inalteradas — custo de embeddings proporcional ao tamanho da base inteira, sem ganho correspondente. Entre os passos 2 e 3 existe uma janela real em que documentos de escopos anteriores ainda não reconciliados ficam recuperáveis — era o filtro de leitura que os escondia. Sem usuários no produto, é aceitável; não descreva essa janela como zero.

Também não use `--limit` neste sync: em `SyncKnowledgeBaseAction`, `partial = limit is not None` desliga a reconciliação, e é a reconciliação que fecha a janela do parágrafo acima — com `--limit`, ela nunca fecharia.

- [ ] **Step 7: Avisar o Yuri**

Não é código, e por isso é fácil esquecer: o combinado da reunião era "te aviso
quando liberar mais coisa". Isso deixa de ser necessário — compartilhar com a
integração passa a bastar, e o efeito aparece no sync seguinte. Sem esse aviso,
ele continua esperando um passo que ninguém precisa mais dar.

- [x] **Step 8: Commit final**

```bash
git add docs/superpowers/plans/2026-08-31-kb-escopo-descoberto.md
git commit -m "docs(plan): marca o plano do escopo descoberto como executado"
```
