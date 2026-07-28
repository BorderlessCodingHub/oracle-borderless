# Recusa Explícita Fora de Escopo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando a pergunta não está coberta pela base, o oráculo responde "não encontrei informações" e explica sobre o que sabe responder — em vez de improvisar a partir dos vizinhos mais próximos.

**Architecture:** Duas camadas. A camada 1 é mecânica: um limiar de distância cosseno (`RAG_MAX_DISTANCE = 0.55`) corta o que não é relevante e, se nada sobra, uma Action devolve um stream de recusa determinístico sem chamar o LLM. A camada 2 cobre o caso ambíguo: o system prompt recebe o texto exato da recusa para o modelo emitir quando o contexto que passou não sustentar a resposta. Junto vem a implementação da ADR-0012 (procedência persistida em `documents`), que é de onde sai a lista de temas e o filtro de escopo na recuperação.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic, pgvector, pytest, UV.

## Global Constraints

- **Spec de referência:** [`docs/superpowers/specs/2026-07-28-recusa-fora-de-escopo-design.md`](../specs/2026-07-28-recusa-fora-de-escopo-design.md). **ADR:** [`docs/adr/0012-escopo-kb-aplicado-na-recuperacao.md`](../../adr/0012-escopo-kb-aplicado-na-recuperacao.md).
- **Limiar default:** `RAG_MAX_DISTANCE = 0.55` (float, configurável em settings).
- **Nomes de coluna (exatos):** `kb_root_page_id`, `kb_section`.
- **Ids de página são sempre normalizados** antes de comparar: sem hífens, minúsculos, sem espaços nas pontas.
- **Títulos de seção levam `.strip()`** — "Conferences " no Notion tem espaço no final.
- **Cópia da recusa é literal** (definida na Task 7); não parafrasear em nenhum lugar.
- **Idioma default é pt-BR**; inglês só quando a heurística detectar mais marcadores em inglês.
- **Nenhuma mudança no frontend nem no `ConversationController`.**
- **Rodar testes com `DB_PORT=5434`** (Postgres local do projeto): `DB_PORT=5434 uv run pytest ...`.
- **A suíte está 100% verde no início deste plano**: 133 unitários + 28 de integração. O banco de teste (`oracle_borderless_test`) foi migrado em 2026-07-28 com `DB_NAME=oracle_borderless_test uv run alembic upgrade head`, o que resolveu as 22 falhas de integração que existiam antes. Se as integrações voltarem a falhar em massa com "relation does not exist", rode esse comando de novo — **não** é regressão do seu código.
- **Migrations novas precisam ser aplicadas nos dois bancos**: o de dev (`uv run alembic upgrade head`) e o de teste (`DB_NAME=oracle_borderless_test uv run alembic upgrade head`). A Task 1 introduz uma migration; sem aplicá-la no banco de teste, as Tasks 4, 5 e 6 falham.
- **Ordem é obrigatória:** as colunas são preenchidas (Task 3) **antes** de o filtro de escopo entrar (Task 4). Inverter deixa o oráculo sem responder nada.

---

### Task 1: Procedência em `documents` — coluna, entity, model, mapper

Adiciona `kb_root_page_id` e `kb_section` como colunas **nullable**, sem nenhuma mudança de comportamento ainda. Nada lê esses campos nesta task.

**Files:**
- Create: `src/support/utils/notion_ids.py`
- Create: `database/migrations/versions/0004_documents_kb_provenance.py`
- Create: `tests/unit/support/utils/__init__.py`
- Create: `tests/unit/support/utils/test_notion_ids.py`
- Modify: `src/domain/documents/entities/document.py`
- Modify: `src/domain/documents/models/document.py`
- Modify: `src/domain/documents/mappers/document_mapper.py`
- Modify: `src/domain/documents/repositories/document_repository.py:40` (tupla de chaves do `upsert`)

**Interfaces:**
- Consumes: nada.
- Produces: `normalize_page_id(value: str | None) -> str | None`; `Document.kb_root_page_id: str | None`; `Document.kb_section: str | None`; colunas `documents.kb_root_page_id` e `documents.kb_section`.

- [ ] **Step 1: Escrever o teste que falha (normalização de id)**

Criar `tests/unit/support/utils/__init__.py` vazio e `tests/unit/support/utils/test_notion_ids.py`:

```python
from src.support.utils.notion_ids import normalize_page_id


def test_removes_dashes_and_lowercases():
    assert normalize_page_id("23D8D655-C889-806D-8828-D527CE6A1529") == (
        "23d8d655c889806d8828d527ce6a1529"
    )


def test_already_normalized_is_unchanged():
    assert normalize_page_id("23d8d655c889806d8828d527ce6a1529") == (
        "23d8d655c889806d8828d527ce6a1529"
    )


def test_strips_surrounding_whitespace():
    assert normalize_page_id("  23d8d655-c889  ") == "23d8d655c889"


def test_none_and_empty_return_none():
    assert normalize_page_id(None) is None
    assert normalize_page_id("") is None
    assert normalize_page_id("   ") is None
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/utils/test_notion_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.support.utils.notion_ids'`

- [ ] **Step 3: Implementar `normalize_page_id`**

Criar `src/support/utils/notion_ids.py`:

```python
"""Normalização de ids de página do Notion.

O MCP devolve UUID com hífens; ids vindos de citação, de env var ou digitados
pelo modelo podem vir sem. Comparar sempre pela forma normalizada.
"""


def normalize_page_id(value: str | None) -> str | None:
    """Id sem hífens, minúsculo e sem espaços nas pontas. `None` se vazio."""
    if value is None:
        return None
    normalized = value.replace("-", "").strip().lower()
    return normalized or None
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/utils/test_notion_ids.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Adicionar os campos na Entity**

Em `src/domain/documents/entities/document.py`, acrescentar dois campos ao final do dataclass (depois de `last_edited_time`, para não quebrar argumentos posicionais):

```python
    last_edited_time: datetime | None = None  # last_edited_time do Notion (sync incremental)
    kb_root_page_id: str | None = None  # root da KB sob o qual foi ingerido (ADR-0012)
    kb_section: str | None = None  # seção = ancestral de 1º nível abaixo do root
```

- [ ] **Step 6: Adicionar as colunas no Model**

Em `src/domain/documents/models/document.py`, depois de `last_edited_time`:

```python
    kb_root_page_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    kb_section: Mapped[str | None] = mapped_column(String(512), nullable=True)
```

- [ ] **Step 7: Levar os campos no Mapper**

Em `src/domain/documents/mappers/document_mapper.py`, acrescentar em **ambos** os métodos.

Em `to_entity(...)`, depois de `last_edited_time=model.last_edited_time,`:

```python
            kb_root_page_id=model.kb_root_page_id,
            kb_section=model.kb_section,
```

Em `to_model_attrs(...)`, depois de `"last_edited_time": entity.last_edited_time,`:

```python
            "kb_root_page_id": entity.kb_root_page_id,
            "kb_section": entity.kb_section,
```

- [ ] **Step 8: Incluir os campos no update do `upsert`**

Em `src/domain/documents/repositories/document_repository.py`, linha 40 — sem isso, re-sync de documento existente nunca grava a procedência:

```python
            for key in (
                "title",
                "content",
                "source_url",
                "status",
                "deleted_at",
                "last_edited_time",
                "kb_root_page_id",
                "kb_section",
            ):
```

- [ ] **Step 9: Escrever a migration**

Criar `database/migrations/versions/0004_documents_kb_provenance.py`:

```python
"""documents.kb_root_page_id + kb_section (procedência de escopo — ADR-0012)

Revision ID: 0004_documents_kb_provenance
Revises: 0003_documents_last_edited_time
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_documents_kb_provenance"
down_revision = "0003_documents_last_edited_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("kb_root_page_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("kb_section", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_documents_kb_root_page_id", "documents", ["kb_root_page_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_documents_kb_root_page_id", table_name="documents")
    op.drop_column("documents", "kb_section")
    op.drop_column("documents", "kb_root_page_id")
```

- [ ] **Step 10: Aplicar a migration e conferir as colunas**

Run:
```bash
uv run alembic upgrade head
docker exec oracle_borderless_db psql -U oracle -d oracle_borderless -c "\d documents"
```
Expected: as colunas `kb_root_page_id` e `kb_section` aparecem; índice `ix_documents_kb_root_page_id` existe.

- [ ] **Step 11: Rodar a suíte unitária inteira**

Run: `DB_PORT=5434 uv run pytest tests/unit -q`
Expected: PASS — 133 testes anteriores + 4 novos = 137.

- [ ] **Step 12: Commit**

```bash
git add src/support/utils/notion_ids.py tests/unit/support/utils/ \
        src/domain/documents/entities/document.py \
        src/domain/documents/models/document.py \
        src/domain/documents/mappers/document_mapper.py \
        src/domain/documents/repositories/document_repository.py \
        database/migrations/versions/0004_documents_kb_provenance.py
git commit -m "feat(kb): persistir procedência de escopo em documents (ADR-0012)"
```

---

### Task 2: Sync grava a procedência

A travessia passa a saber de qual seção cada página descende, e a ingestão persiste isso junto do root vigente.

**Files:**
- Modify: `src/support/clients/notion/notion_client.py` (dataclass `NotionPage`, `_collect_scope`)
- Modify: `src/domain/documents/mappers/notion_page_mapper.py`
- Test: `tests/unit/support/clients/notion/test_notion_client_scope.py` (acrescentar)
- Create: `tests/unit/domain/documents/mappers/test_notion_page_mapper_provenance.py`

**Interfaces:**
- Consumes: `normalize_page_id` (Task 1); `Document.kb_root_page_id`, `Document.kb_section` (Task 1).
- Produces: `NotionPage.section: str | None`; `NotionPageMapper.to_document(page, root_page_id)` — **assinatura muda**, ganha segundo parâmetro obrigatório.

- [ ] **Step 1: Escrever o teste que falha (propagação da seção)**

Acrescentar ao final de `tests/unit/support/clients/notion/test_notion_client_scope.py`:

```python
@pytest.mark.asyncio
async def test_collect_scope_propagates_section_from_first_level():
    # root → [Bootcamps, Programs] ; Bootcamps → [Web3] ; Web3 → [Edição 02]
    tree = {
        "root": [_child_page("BC", "Bootcamps"), _child_page("PR", "Programs")],
        "BC": [_child_page("W3", "Web3 Global Developer")],
        "W3": [_child_page("E2", "Edição #02")],
        "PR": [],
        "E2": [],
    }
    pages = await NotionClient()._collect_scope(_make_call(tree, []), "root")
    section_by_id = {p.id: p.section for p in pages}

    assert section_by_id["BC"] == "Bootcamps"   # filho direto: seção é ele mesmo
    assert section_by_id["PR"] == "Programs"
    assert section_by_id["W3"] == "Bootcamps"   # neto herda
    assert section_by_id["E2"] == "Bootcamps"   # bisneto herda


@pytest.mark.asyncio
async def test_collect_scope_strips_section_title():
    tree = {"root": [_child_page("CF", "Conferences ")], "CF": []}
    pages = await NotionClient()._collect_scope(_make_call(tree, []), "root")
    assert pages[0].section == "Conferences"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/clients/notion/test_notion_client_scope.py -v -k section`
Expected: FAIL — `AttributeError: 'NotionPage' object has no attribute 'section'`

- [ ] **Step 3: Adicionar `section` ao `NotionPage`**

Em `src/support/clients/notion/notion_client.py`, no dataclass `NotionPage`, depois de `last_edited_time`:

```python
    last_edited_time: datetime | None = None
    section: str | None = None  # ancestral de 1º nível abaixo do root (ADR-0012)
```

- [ ] **Step 4: Propagar a seção em `_collect_scope`**

Substituir o corpo de `_collect_scope` em `src/support/clients/notion/notion_client.py`. A pilha passa a carregar `(page_id, secao_herdada)`; `None` na raiz significa "o próximo nível define a seção":

```python
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
                    )
                )
                stack.append((block["id"], section))
        return approved
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/clients/notion/ -v`
Expected: PASS — os 2 novos testes e todos os anteriores do arquivo.

- [ ] **Step 6: Escrever o teste que falha (mapper)**

Criar `tests/unit/domain/documents/mappers/test_notion_page_mapper_provenance.py`:

```python
from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.support.clients.notion.notion_client import NotionPage

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


def _page(**over) -> NotionPage:
    base = dict(
        id="p1",
        title="Web3 Bootcamp",
        content="conteúdo",
        url="https://notion.so/p1",
        is_approved=True,
        section="Bootcamps",
    )
    base.update(over)
    return NotionPage(**base)


def test_maps_section_and_normalized_root():
    doc = NotionPageMapper.to_document(_page(), root_page_id=ROOT)
    assert doc.kb_section == "Bootcamps"
    assert doc.kb_root_page_id == "23d8d655c889806d8828d527ce6a1529"  # sem hífens


def test_missing_section_maps_to_none():
    doc = NotionPageMapper.to_document(_page(section=None), root_page_id=ROOT)
    assert doc.kb_section is None
```

- [ ] **Step 7: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/documents/mappers/test_notion_page_mapper_provenance.py -v`
Expected: FAIL — `TypeError: to_document() got an unexpected keyword argument 'root_page_id'`

- [ ] **Step 8: Atualizar o mapper**

Substituir `src/domain/documents/mappers/notion_page_mapper.py` inteiro:

```python
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.documents.entities.document import Document
from src.support.clients.notion.notion_client import NotionPage
from src.support.utils.notion_ids import normalize_page_id


class NotionPageMapper:
    @staticmethod
    def to_document(page: NotionPage, root_page_id: str) -> Document:
        now = datetime.now(timezone.utc)
        return Document(
            uuid=uuid4(),
            notion_page_id=page.id,
            title=page.title,
            content=page.content,
            source_url=page.url,
            status="approved" if page.is_approved else "pending",
            created_at=now,
            updated_at=now,
            deleted_at=None,
            last_edited_time=page.last_edited_time,
            kb_root_page_id=normalize_page_id(root_page_id),
            kb_section=page.section,
        )
```

- [ ] **Step 9: Atualizar o chamador no sync**

Em `src/domain/documents/actions/sync_knowledge_base_action.py`, o `execute` precisa do root para repassar ao mapper. Trocar o início do método e a chamada:

Depois de `approved = await self.notion.list_approved_pages()`, acrescentar:

```python
        root_page_id = settings.NOTION_KB_ROOT_PAGE_ID or ""
```

E trocar a linha `await self.ingest.execute(NotionPageMapper.to_document(full))` por:

```python
                        await self.ingest.execute(
                            NotionPageMapper.to_document(full, root_page_id)
                        )
```

Acrescentar o import no topo do arquivo:

```python
from src.support.core.settings import settings
```

Nota: `full` (de `get_page`) não traz `section` — quem tem a seção é `page`, da travessia. Preservar:

```python
                        full = await self.notion.get_page(page.id)
                        full.section = page.section
```

- [ ] **Step 10: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit -q`
Expected: PASS — 137 anteriores + 4 novos = 141.

- [ ] **Step 11: Commit**

```bash
git add src/support/clients/notion/notion_client.py \
        src/domain/documents/mappers/notion_page_mapper.py \
        src/domain/documents/actions/sync_knowledge_base_action.py \
        tests/unit/support/clients/notion/test_notion_client_scope.py \
        tests/unit/domain/documents/mappers/test_notion_page_mapper_provenance.py
git commit -m "feat(kb): sync grava root e seção de cada documento"
```

---

### Task 3: Backfill — popular a procedência na base atual

Task **operacional**, sem código. Preenche as colunas nos 42 documentos ativos. Precisa acontecer **antes** da Task 4, senão o filtro de escopo zera a base.

**Files:** nenhum.

**Interfaces:**
- Consumes: Task 2 (sync que grava procedência).
- Produces: 42 documentos ativos com `kb_root_page_id` preenchido — pré-condição da Task 4.

- [ ] **Step 1: Backup antes de mexer**

Run:
```bash
docker exec oracle_borderless_db pg_dump -U oracle -d oracle_borderless \
  -t documents -t document_chunks > /tmp/kb_backup_task3.sql
ls -lh /tmp/kb_backup_task3.sql
```
Expected: arquivo de dezenas de MB criado.

- [ ] **Step 2: Rodar o sync com `--force`**

`--force` é necessário: sem ele, os 42 documentos são considerados atualizados (`inalteradas=42`) e a ingestão — que é quem grava a procedência — não roda.

Run: `uv run python cli.py knowledge:sync --force`
Expected: `Sync concluído: aprovadas=42 ingeridas=42 inalteradas=0 removidas=0 falhas=0`

- [ ] **Step 3: Conferir que a procedência foi gravada**

Run:
```bash
docker exec oracle_borderless_db psql -U oracle -d oracle_borderless -c "
select kb_section, count(*)
from documents where deleted_at is null
group by 1 order by 2 desc;"
```
Expected: as seções aparecem (Mentorship, Bootcamps, Programs, Masterclasses, Conferences), somando 42, **nenhuma linha com `kb_section` nulo**.

- [ ] **Step 4: Conferir que não sobrou root nulo entre os ativos**

Run:
```bash
docker exec oracle_borderless_db psql -U oracle -d oracle_borderless -c "
select count(*) as ativos_sem_root
from documents where deleted_at is null and kb_root_page_id is null;"
```
Expected: `0`. Se não for 0, **parar** — a Task 4 tornaria esses documentos irrecuperáveis.

---

### Task 4: Recuperação filtra pelo root atual (ADR-0012)

**Files:**
- Modify: `src/domain/documents/repositories/document_chunk_repository.py:27-42`
- Modify: `tests/integration/conftest.py`
- Create: `tests/integration/domain/documents/test_chunk_repository_scope_filter.py`

**Interfaces:**
- Consumes: `normalize_page_id` (Task 1); coluna `kb_root_page_id` populada (Task 3).
- Produces: `search_similar` passa a devolver só chunks do root vigente; fixture
  `seed_document_with_chunk(title, kb_root_page_id=None, kb_section=None, embedding=None, soft_deleted=False)`
  usada também pelas Tasks 5 e 6.

- [ ] **Step 1: Criar a fixture compartilhada**

Acrescentar em `tests/integration/conftest.py`. Já contempla `kb_section`,
`embedding` e `soft_deleted` porque as Tasks 5 e 6 usam os três — criar completa
agora evita mexer no conftest três vezes.

Nos imports do topo do arquivo:

```python
from datetime import datetime
from uuid import uuid4

from src.domain.documents.entities.document import Document
from src.domain.documents.entities.document_chunk import DocumentChunk
from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.utils.notion_ids import normalize_page_id
```

E a fixture ao final do arquivo:

```python
@pytest.fixture
def seed_document_with_chunk(db_session):
    """Insere um documento aprovado + 1 chunk e devolve o Document persistido.

    Fixture síncrona que devolve uma corrotina: o `db_session` já foi resolvido
    pelo pytest-asyncio, então cada chamada roda dentro da mesma transação e o
    rollback do `db_session` limpa tudo no fim do teste.
    """

    async def _seed(
        title: str,
        kb_root_page_id: str | None = None,
        kb_section: str | None = None,
        embedding: list[float] | None = None,
        soft_deleted: bool = False,
    ) -> Document:
        now = datetime(2026, 1, 1)
        document = await DocumentRepository().upsert(
            Document(
                uuid=uuid4(),
                notion_page_id=f"pid-{uuid4()}",
                title=title,
                content="conteúdo",
                source_url="https://notion.so/x",
                status="approved",
                created_at=now,
                updated_at=now,
                deleted_at=now if soft_deleted else None,
                last_edited_time=None,
                kb_root_page_id=normalize_page_id(kb_root_page_id),
                kb_section=kb_section,
            )
        )
        await db_session.flush()

        vector = embedding if embedding is not None else [1.0] + [0.0] * (settings.EMBEDDING_DIM - 1)
        await DocumentChunkRepository().replace_for_document(
            document.uuid,
            [DocumentChunk(uuid4(), document.uuid, 0, f"trecho de {title}", vector)],
        )
        await db_session.flush()
        return document

    return _seed
```

- [ ] **Step 2: Escrever o teste que falha**

Criar `tests/integration/domain/documents/test_chunk_repository_scope_filter.py`. Seguir o padrão dos testes vizinhos em `tests/integration/domain/documents/` para fixtures de sessão:

```python
"""Escopo na recuperação: documento de outro root não é recuperado (ADR-0012)."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"

# Vetor NÃO-nulo: cosine_distance contra vetor zero é indefinida (NaN no pgvector)
# e tornaria a ordenação — e o limiar da Task 5 — imprevisíveis.
_QUERY = [1.0] + [0.0] * 1535


@pytest.mark.asyncio
async def test_chunk_of_another_root_is_not_retrieved(monkeypatch, seed_document_with_chunk):
    """`seed_document_with_chunk(kb_root_page_id=...)` insere doc + 1 chunk."""
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)
    titles = {h.citation.title for h in hits}

    assert "Do root atual" in titles
    assert "De outro root" not in titles


@pytest.mark.asyncio
async def test_document_without_provenance_is_not_retrieved(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)
    assert "Sem procedência" not in {h.citation.title for h in hits}
```

- [ ] **Step 3: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_scope_filter.py -v`
Expected: FAIL — "De outro root" e "Sem procedência" aparecem nos resultados.

- [ ] **Step 4: Aplicar o filtro**

Em `src/domain/documents/repositories/document_chunk_repository.py`, no `search_similar`, acrescentar o import no topo do arquivo:

```python
from src.support.utils.notion_ids import normalize_page_id
```

E trocar o `.where(...)` do statement por:

```python
        stmt = (
            select(
                DocumentChunkModel.content,
                DocumentModel.title,
                DocumentModel.source_url,
                DocumentModel.notion_page_id,
            )
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                # Escopo como invariante de leitura (ADR-0012): documento de outro
                # root — ou sem procedência — não é servido, mesmo sem sync.
                DocumentModel.kb_root_page_id
                == normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID),
            )
            .order_by(DocumentChunkModel.embedding.cosine_distance(embedding))
            .limit(limit)
        )
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_scope_filter.py -v`
Expected: PASS (2 testes)

- [ ] **Step 6: Conferir que o oráculo real ainda recupera**

Run:
```bash
uv run python - <<'PY'
import asyncio
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as s:
        CurrentAsyncSessionContext.set(s)
        hits = await SearchKnowledgeBaseAction(embeddings=get_embeddings_client()).execute(
            "o que é o Web3 Bootcamp?"
        )
        print(len(hits), sorted({h.citation.title for h in hits}))
        CurrentAsyncSessionContext.clear()

asyncio.run(main())
PY
```
Expected: 6 trechos, títulos de Products. **Se vier 0, a Task 3 não foi feita** — não siga adiante.

- [ ] **Step 7: Commit**

```bash
git add src/domain/documents/repositories/document_chunk_repository.py \
        tests/integration/domain/documents/test_chunk_repository_scope_filter.py \
        tests/integration/conftest.py
git commit -m "feat(kb): filtrar recuperação pelo root vigente (ADR-0012)"
```

---

### Task 5: Limiar de distância na recuperação

**Files:**
- Modify: `src/support/core/settings.py:69` (junto de `RAG_TOP_K`)
- Modify: `src/domain/documents/repositories/document_chunk_repository.py`
- Modify: `.env.example`
- Create: `tests/integration/domain/documents/test_chunk_repository_threshold.py`

**Interfaces:**
- Consumes: `search_similar` (Task 4).
- Produces: `settings.RAG_MAX_DISTANCE: float`; `search_similar` devolve `[]` quando nada está abaixo do limiar.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/integration/domain/documents/test_chunk_repository_threshold.py`:

```python
"""Limiar de distância: chunk distante demais não vira contexto."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_returns_nothing_when_everything_is_beyond_the_threshold(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    monkeypatch.setattr(settings, "RAG_MAX_DISTANCE", 0.05, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    # embedding do chunk é [1.0, 0, 0, ...]; a query é o oposto -> distância ~2.0
    await seed_document_with_chunk(
        title="Distante", kb_root_page_id=ROOT, embedding=[1.0] + [0.0] * 1535
    )
    query = [-1.0] + [0.0] * 1535

    assert await DocumentChunkRepository().search_similar(query, top_k=10) == []


@pytest.mark.asyncio
async def test_returns_the_chunk_when_within_the_threshold(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    monkeypatch.setattr(settings, "RAG_MAX_DISTANCE", 0.55, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(
        title="Próximo", kb_root_page_id=ROOT, embedding=[1.0] + [0.0] * 1535
    )
    query = [1.0] + [0.0] * 1535  # idêntico -> distância ~0

    hits = await DocumentChunkRepository().search_similar(query, top_k=10)
    assert [h.citation.title for h in hits] == ["Próximo"]
```

A fixture `seed_document_with_chunk` (Task 4, Step 1) já aceita `embedding=`.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_threshold.py -v`
Expected: FAIL no primeiro teste — devolve o chunk distante em vez de `[]`.

- [ ] **Step 3: Adicionar o setting**

Em `src/support/core/settings.py`, logo abaixo de `RAG_TOP_K: int = 6`:

```python
    # Distância cosseno máxima para um chunk virar contexto. Calibrado em
    # 2026-07-28: pergunta legítima ficou <= 0.532, pergunta sem relação >= 0.615.
    RAG_MAX_DISTANCE: float = 0.55
```

- [ ] **Step 4: Documentar no `.env.example`**

Acrescentar perto das demais chaves de RAG:

```
# Distância cosseno máxima para um trecho ser considerado relevante (0..2).
# Acima disso o oráculo responde que não encontrou. Default: 0.55
RAG_MAX_DISTANCE=0.55
```

- [ ] **Step 5: Aplicar o limiar na query**

Em `src/domain/documents/repositories/document_chunk_repository.py`, no `search_similar`,
extrair a expressão de distância e usá-la nos dois lugares (filtro e ordenação).

> ⚠️ **A Task 4 já introduziu a guarda de fail-closed** (`root is None` → `return []`,
> porque `== None` compila para `IS NULL` e casaria justamente com os documentos sem
> procedência). **Preserve-a.** O bloco abaixo mostra só a mudança do limiar; leia o
> método como ele está no arquivo e acrescente o predicado de distância sem remover a
> guarda nem a comparação de root.

```python
    async def search_similar(
        self, embedding: list[float], top_k: int | None = None
    ) -> list[KnowledgeSnippet]:
        limit = top_k if top_k is not None else settings.RAG_TOP_K
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            # Guarda da Task 4 — NÃO remover.
            return []
        distance = DocumentChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(
                DocumentChunkModel.content,
                DocumentModel.title,
                DocumentModel.source_url,
                DocumentModel.notion_page_id,
            )
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_root_page_id == root,
                # Sem limiar, top-k sempre devolve algo: pergunta fora do assunto
                # recuperaria os vizinhos menos distantes e viraria contexto.
                distance <= settings.RAG_MAX_DISTANCE,
            )
            .order_by(distance)
            .limit(limit)
        )
```

Se a forma exata da guarda na Task 4 divergir deste bloco, **a do arquivo vence** —
ajuste apenas o que diz respeito ao limiar.

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_threshold.py -v`
Expected: PASS (2 testes)

- [ ] **Step 7: Commit**

```bash
git add src/support/core/settings.py .env.example \
        src/domain/documents/repositories/document_chunk_repository.py \
        tests/integration/domain/documents/test_chunk_repository_threshold.py
git commit -m "feat(rag): limiar de distância para o que vira contexto"
```

---

### Task 6: `ListKnowledgeSectionsAction`

**Files:**
- Create: `src/domain/documents/actions/list_knowledge_sections_action.py`
- Modify: `src/domain/documents/repositories/document_repository.py`
- Modify: `src/domain/documents/actions/__init__.py`
- Create: `tests/integration/domain/documents/test_list_knowledge_sections.py`

**Interfaces:**
- Consumes: coluna `kb_section` (Task 1), populada (Task 3).
- Produces: `ListKnowledgeSectionsAction().execute() -> list[str]` — seções distintas, `.strip()`, ordenadas alfabeticamente, sem nulos, só de documentos ativos do root vigente.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/integration/domain/documents/test_list_knowledge_sections.py`:

```python
"""Lista de temas que o oráculo cobre — alimenta a mensagem de recusa."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_lists_distinct_sections_sorted(monkeypatch, seed_document_with_chunk):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="d1", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(title="d2", kb_root_page_id=ROOT, kb_section="Bootcamps")
    await seed_document_with_chunk(title="d3", kb_root_page_id=ROOT, kb_section="Programs")

    assert await ListKnowledgeSectionsAction().execute() == ["Bootcamps", "Programs"]


@pytest.mark.asyncio
async def test_ignores_soft_deleted_and_null_sections(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="viva", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(
        title="morta", kb_root_page_id=ROOT, kb_section="Fantasma", soft_deleted=True
    )
    await seed_document_with_chunk(title="sem", kb_root_page_id=ROOT, kb_section=None)

    assert await ListKnowledgeSectionsAction().execute() == ["Programs"]
```

A fixture `seed_document_with_chunk` (Task 4, Step 1) já aceita `kb_section=` e `soft_deleted=`.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_list_knowledge_sections.py -v`
Expected: FAIL — `ModuleNotFoundError: ...list_knowledge_sections_action`

- [ ] **Step 3: Adicionar a query no repositório**

Em `src/domain/documents/repositories/document_repository.py`, acrescentar o import:

```python
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id
```

E o método:

```python
    async def list_sections(self) -> list[str]:
        """Seções distintas dos documentos ativos do root vigente, ordenadas."""
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            # Mesma guarda de search_similar: `== None` compila para `IS NULL` e
            # casaria justamente com os documentos sem procedência. Não simplificar.
            return []
        result = await self.session.execute(
            select(DocumentModel.kb_section)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_section.is_not(None),
                DocumentModel.kb_root_page_id == root,
            )
            .distinct()
        )
        return sorted({(s or "").strip() for s in result.scalars().all() if (s or "").strip()})
```

- [ ] **Step 4: Criar a Action**

Criar `src/domain/documents/actions/list_knowledge_sections_action.py`:

```python
from src.domain.documents.repositories.document_repository import DocumentRepository


class ListKnowledgeSectionsAction:
    """Temas cobertos pela base — os ancestrais de 1º nível abaixo do root.

    Fronteira pública do subdomínio `documents` para quem precisa dizer ao
    usuário sobre o que o oráculo responde.
    """

    def __init__(self, documents=None) -> None:
        self.documents = documents or DocumentRepository()

    async def execute(self) -> list[str]:
        return await self.documents.list_sections()
```

- [ ] **Step 5: Exportar no `__init__`**

Substituir `src/domain/documents/actions/__init__.py`:

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

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_list_knowledge_sections.py -v`
Expected: PASS (2 testes)

- [ ] **Step 7: Commit**

```bash
git add src/domain/documents/actions/list_knowledge_sections_action.py \
        src/domain/documents/actions/__init__.py \
        src/domain/documents/repositories/document_repository.py \
        tests/integration/domain/documents/test_list_knowledge_sections.py \
        tests/integration/conftest.py
git commit -m "feat(kb): action que lista os temas cobertos pela base"
```

---

### Task 7: Serviço da cópia de recusa (puro)

Domain Service sem I/O: recebe a lista de temas e a pergunta, devolve o texto. Testável sem banco e sem LLM.

**Files:**
- Create: `src/domain/conversations/services/out_of_scope_reply.py`
- Modify: `src/domain/conversations/services/__init__.py`
- Create: `tests/unit/domain/conversations/services/test_out_of_scope_reply.py`

**Interfaces:**
- Consumes: nada (função pura).
- Produces: `detect_language(text: str) -> str` (`"pt"` | `"en"`); `build_out_of_scope_reply(sections: list[str], question: str) -> str`; constante `OUT_OF_SCOPE_OPENING_PT: str`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/domain/conversations/services/__init__.py` vazio (se não existir) e `tests/unit/domain/conversations/services/test_out_of_scope_reply.py`:

```python
from src.domain.conversations.services.out_of_scope_reply import (
    build_out_of_scope_reply,
    detect_language,
)

SECOES = ["Bootcamps", "Conferences", "Masterclasses", "Mentorship", "Programs"]


def test_detects_portuguese():
    assert detect_language("qual é o processo de renovação do PSP?") == "pt"


def test_detects_english():
    assert detect_language("what is the renewal process for PSP?") == "en"


def test_defaults_to_portuguese_when_ambiguous():
    assert detect_language("PSP?") == "pt"
    assert detect_language("") == "pt"


def test_portuguese_copy_lists_every_section():
    text = build_out_of_scope_reply(SECOES, "qual é o processo de renovação?")
    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    for secao in SECOES:
        assert secao in text
    assert "Mentorship e Programs" in text  # conjunção em português (último par)
    assert "Tente perguntar sobre um desses temas." in text


def test_english_copy_uses_english_conjunction():
    text = build_out_of_scope_reply(SECOES, "what is the renewal process?")
    assert text.startswith("I didn't find information about this in the knowledge base.")
    assert "Mentorship and Programs" in text


def test_section_titles_are_stripped():
    text = build_out_of_scope_reply(["Conferences ", " Programs"], "o que é isso?")
    assert "Conferences e Programs" in text
    assert "Conferences  e" not in text


def test_single_section_has_no_conjunction():
    text = build_out_of_scope_reply(["Programs"], "o que é isso?")
    assert "sobre os produtos e programas do ecossistema — Programs." in text


def test_empty_sections_degrades_gracefully():
    text = build_out_of_scope_reply([], "o que é isso?")
    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    assert "—" not in text  # sem lista vazia pendurada
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations/services/test_out_of_scope_reply.py -v`
Expected: FAIL — `ModuleNotFoundError: ...out_of_scope_reply`

- [ ] **Step 3: Implementar o serviço**

Criar `src/domain/conversations/services/out_of_scope_reply.py`:

```python
"""Resposta padrão quando a pergunta não está coberta pela base.

Função pura: recebe os temas já resolvidos e a pergunta, devolve o texto. Sem
I/O e sem LLM — a recusa é instantânea e a cópia é exatamente esta.
"""

import re

# Marcadores disjuntos: nenhuma palavra aparece nos dois conjuntos, senão a
# contagem empata à toa. "a" ficou fora por ser artigo nos dois idiomas.
_PT_MARKERS = frozenset(
    {
        "o", "os", "as", "de", "da", "do", "que", "qual", "quais", "como",
        "por", "para", "não", "é", "um", "uma", "quem", "onde", "quando", "sobre",
    }
)
_EN_MARKERS = frozenset(
    {
        "the", "an", "of", "what", "which", "how", "why", "for", "is", "are",
        "does", "who", "where", "when", "can", "about",
    }
)

_WORD_RE = re.compile(r"[a-zà-ÿ]+")

OUT_OF_SCOPE_OPENING_PT = "Não encontrei informações sobre isso na base de conhecimento."
_OPENING_EN = "I didn't find information about this in the knowledge base."

_BODY_PT = "Eu respondo sobre os produtos e programas do ecossistema — {temas}."
_BODY_EN = "I answer questions about the ecosystem's products and programs — {temas}."
_BODY_PT_EMPTY = "Eu respondo sobre os produtos e programas do ecossistema."
_BODY_EN_EMPTY = "I answer questions about the ecosystem's products and programs."

_CLOSING_PT = "Tente perguntar sobre um desses temas."
_CLOSING_EN = "Try asking about one of those topics."


def detect_language(text: str) -> str:
    """`"en"` só quando o inglês tem mais marcadores; pt-BR é o default."""
    words = _WORD_RE.findall(text.lower())
    pt = sum(1 for w in words if w in _PT_MARKERS)
    en = sum(1 for w in words if w in _EN_MARKERS)
    return "en" if en > pt else "pt"


def _join(items: list[str], conjunction: str) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"


def build_out_of_scope_reply(sections: list[str], question: str) -> str:
    cleaned = [s.strip() for s in sections if s and s.strip()]
    english = detect_language(question) == "en"

    opening = _OPENING_EN if english else OUT_OF_SCOPE_OPENING_PT
    closing = _CLOSING_EN if english else _CLOSING_PT
    if cleaned:
        temas = _join(cleaned, "and" if english else "e")
        body = (_BODY_EN if english else _BODY_PT).format(temas=temas)
    else:
        body = _BODY_EN_EMPTY if english else _BODY_PT_EMPTY

    return f"{opening}\n\n{body} {closing}"
```

- [ ] **Step 4: Exportar no `__init__`**

Em `src/domain/conversations/services/__init__.py` (hoje vazio):

```python
from src.domain.conversations.services.out_of_scope_reply import (
    OUT_OF_SCOPE_OPENING_PT,
    build_out_of_scope_reply,
    detect_language,
)

__all__ = ["OUT_OF_SCOPE_OPENING_PT", "build_out_of_scope_reply", "detect_language"]
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations/services/ -v`
Expected: PASS (8 testes)

- [ ] **Step 6: Commit**

```bash
git add src/domain/conversations/services/out_of_scope_reply.py \
        src/domain/conversations/services/__init__.py \
        tests/unit/domain/conversations/services/
git commit -m "feat(oracle): cópia da recusa fora de escopo (pt-BR e inglês)"
```

---

### Task 8: Gatilho da recusa na `AnswerQuestionAction`

O coração da feature — **e a guarda do gate**, que impede "oi" de virar recusa.

**Files:**
- Modify: `src/domain/conversations/actions/answer_question_action.py`
- Create: `tests/unit/domain/conversations/actions/test_answer_question_out_of_scope.py`

**Interfaces:**
- Consumes: `build_out_of_scope_reply` (Task 7); `ListKnowledgeSectionsAction` (Task 6); `AgentStreamChunk` (existente).
- Produces: `AnswerQuestionAction.__init__` ganha o parâmetro opcional `sections=None`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/domain/conversations/actions/test_answer_question_out_of_scope.py`:

```python
"""Recusa quando a base não cobre — e a guarda que evita recusar saudação."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from tests.fakes.fake_oracle_engine import FakeOracleEngine
from tests.fakes.fake_retrieval_gate import FakeRetrievalGate


class _FakeSearch:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.called = False

    async def execute(self, question, top_k=None):
        self.called = True
        return self.hits


class _FakeSections:
    async def execute(self):
        return ["Bootcamps", "Programs"]


class _FakeConvRepo:
    async def create(self, conversation):
        return conversation

    async def get_by_id(self, cid):
        return None


class _FakeMsgRepo:
    def __init__(self):
        self.appended = []

    async def load_recent(self, cid):
        return []

    async def append(self, message):
        self.appended.append(message)


def _build(gate, search):
    action = AnswerQuestionAction(
        engine=FakeOracleEngine(answer="resposta do motor"),
        search=search,
        gate=gate,
        sections=_FakeSections(),
    )
    action.conversations = _FakeConvRepo()
    action.messages = _FakeMsgRepo()
    return action


async def _collect(stream):
    text, citations = "", None
    async for chunk in stream:
        if chunk.type == "text":
            text += chunk.text
        elif chunk.type == "sources":
            citations = chunk.citations
    return text, citations


@pytest.mark.asyncio
async def test_refuses_when_retrieval_wanted_but_nothing_found():
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=[]))

    _, stream = await action.execute("qual a capital da Austrália?", None, None)
    text, citations = await _collect(stream)

    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    assert "Bootcamps e Programs" in text
    assert citations == []
    assert "resposta do motor" not in text


@pytest.mark.asyncio
async def test_greeting_is_not_refused_even_though_knowledge_is_empty():
    """A guarda: retrieve=False também dá knowledge vazio, mas deve ir ao motor."""
    search = _FakeSearch(hits=[])
    action = _build(FakeRetrievalGate(retrieve=False), search)

    _, stream = await action.execute("oi, tudo bem?", None, None)
    text, _ = await _collect(stream)

    assert "resposta do motor" in text
    assert "Não encontrei informações" not in text
    assert search.called is False


@pytest.mark.asyncio
async def test_goes_to_the_engine_when_knowledge_was_found():
    from src.domain.shared.value_objects.citation import Citation
    from src.support.agent.ports import KnowledgeSnippet

    hits = [KnowledgeSnippet("trecho", Citation("notion", "Doc", "u", "s", "p"))]
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=hits))

    _, stream = await action.execute("o que é o Web3 Bootcamp?", None, None)
    text, _ = await _collect(stream)

    assert "resposta do motor" in text


@pytest.mark.asyncio
async def test_refusal_answers_in_english_for_an_english_question():
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=[]))

    _, stream = await action.execute("what is the capital of Australia?", None, None)
    text, _ = await _collect(stream)

    assert text.startswith("I didn't find information about this in the knowledge base.")
    assert "Bootcamps and Programs" in text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations/actions/test_answer_question_out_of_scope.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'sections'`

- [ ] **Step 3: Implementar o gatilho**

Em `src/domain/conversations/actions/answer_question_action.py`:

Acrescentar aos imports:

```python
from typing import AsyncIterator
from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply
from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
```

Acrescentar, no nível do módulo (depois de `_TITLE_MAX = 80`):

```python
async def _refusal_stream(text: str) -> AsyncIterator[AgentStreamChunk]:
    """Stream de recusa no mesmo contrato do motor: texto + sources vazio."""
    yield AgentStreamChunk(type="text", text=text)
    yield AgentStreamChunk(type="sources", citations=[])
```

Trocar a assinatura do `__init__` e acrescentar o campo:

```python
    def __init__(
        self,
        engine: OracleEnginePort,
        search: SearchKnowledgeBaseAction,
        gate: RetrievalGatePort,
        sections=None,
    ) -> None:
        self.engine = engine
        self.search = search
        self.gate = gate
        self.sections = sections or ListKnowledgeSectionsAction()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
```

Trocar o bloco final do `execute` (o `if decision.retrieve: ... return ...`) por:

```python
        if decision.retrieve:
            knowledge = await self.search.execute(decision.search_query)  # query reescrita
            if not knowledge:
                # Nada passou do limiar: recusa determinística, sem chamar o LLM.
                # Só vale quando o gate PEDIU busca — `retrieve=False` (saudação,
                # agradecimento) também dá knowledge vazio e deve ir ao motor.
                reply = build_out_of_scope_reply(await self.sections.execute(), question)
                return conversation.uuid, _refusal_stream(reply)
        else:
            knowledge = []  # nada injetado — sem poluição de contexto

        return conversation.uuid, self.engine.stream_answer(question, history, knowledge)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations/ -v`
Expected: PASS — os 4 novos e todos os testes anteriores de `test_answer_question_action.py`.

- [ ] **Step 5: Rodar a suíte unitária inteira**

Run: `DB_PORT=5434 uv run pytest tests/unit -q`
Expected: PASS, sem regressão.

- [ ] **Step 6: Commit**

```bash
git add src/domain/conversations/actions/answer_question_action.py \
        tests/unit/domain/conversations/actions/test_answer_question_out_of_scope.py
git commit -m "feat(oracle): recusar quando a base não cobre a pergunta"
```

---

### Task 9: Camada 2 — o prompt cobre o caso ambíguo

Pergunta que passa do limiar mas cujo contexto não responde (ex.: "renovação do PSP") deve produzir a mesma mensagem, agora por decisão do modelo.

**Files:**
- Modify: `src/support/agent/prompts.py`
- Create: `tests/unit/support/agent/test_prompts_refusal.py`

**Interfaces:**
- Consumes: `OUT_OF_SCOPE_OPENING_PT` (Task 7).
- Produces: `SYSTEM_PROMPT` contendo o texto literal da recusa.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/support/agent/test_prompts_refusal.py`:

```python
"""O prompt tem de carregar a cópia exata da recusa, senão a camada 2 improvisa."""

from src.domain.conversations.services.out_of_scope_reply import OUT_OF_SCOPE_OPENING_PT
from src.support.agent.prompts import SYSTEM_PROMPT


def test_prompt_contains_the_literal_refusal_opening():
    assert OUT_OF_SCOPE_OPENING_PT in SYSTEM_PROMPT


def test_prompt_instructs_to_use_it_verbatim():
    assert "literalmente" in SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/agent/test_prompts_refusal.py -v`
Expected: FAIL — a frase não está no prompt.

- [ ] **Step 3: Atualizar o prompt**

Em `src/support/agent/prompts.py`, trocar a regra nº 2 e acrescentar um bloco. A regra 2 passa a ser:

```
2. SEMPRE cite as fontes que usou. Se o contexto fornecido não sustentar a
   resposta, NÃO especule: use a RESPOSTA PADRÃO abaixo, literalmente.
```

E acrescentar, logo antes de `FLUXO:`:

```
RESPOSTA PADRÃO (quando o contexto não responde à pergunta):
Comece a resposta exatamente com esta frase, sem reformular:

Não encontrei informações sobre isso na base de conhecimento.

Depois dela, diga em uma frase sobre o que você responde (os produtos e programas
do ecossistema) e convide a pessoa a perguntar sobre esses temas. Se a pergunta
estiver em inglês, use: "I didn't find information about this in the knowledge
base." e siga em inglês.

Isso vale inclusive quando o contexto fornecido é sobre um assunto PRÓXIMO mas
não responde ao que foi perguntado — é melhor recusar do que preencher a lacuna.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/agent/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/support/agent/prompts.py tests/unit/support/agent/test_prompts_refusal.py
git commit -m "feat(oracle): prompt emite a recusa padrão quando o contexto não responde"
```

---

### Task 10: Comando `knowledge:calibrate` e verificação de ponta a ponta

Versiona a medição que embasou o 0.55, para que recalibrar seja rodar um comando.

**Files:**
- Create: `src/app/console/commands/knowledge_calibrate_command.py`
- Create: `tests/unit/app/console/test_knowledge_calibrate_command.py`

**Interfaces:**
- Consumes: `settings.RAG_MAX_DISTANCE` (Task 5); `EmbeddingsClient`; `DocumentChunkModel`.
- Produces: comando CLI `knowledge:calibrate`; função `format_row(distance: float, question: str, title: str, threshold: float) -> str`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/unit/app/console/__init__.py` vazio (se não existir) e `tests/unit/app/console/test_knowledge_calibrate_command.py`:

```python
from src.app.console.commands.knowledge_calibrate_command import format_row


def test_marks_rows_below_the_threshold_as_passing():
    assert format_row(0.31, "o que é o bootcamp?", "Web3", 0.55).startswith("PASSA")


def test_marks_rows_above_the_threshold_as_refused():
    assert format_row(0.81, "capital da Austrália?", "Módulo", 0.55).startswith("RECUSA")


def test_row_shows_distance_with_three_decimals():
    assert "0.310" in format_row(0.31, "q", "t", 0.55)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/app/console/test_knowledge_calibrate_command.py -v`
Expected: FAIL — `ModuleNotFoundError: ...knowledge_calibrate_command`

- [ ] **Step 3: Implementar o comando**

Criar `src/app/console/commands/knowledge_calibrate_command.py`:

```python
"""Mede a distância do melhor chunk para um conjunto fixo de perguntas.

Serve para reconferir `RAG_MAX_DISTANCE` quando a base muda de tamanho: a
calibração de 2026-07-28 valia para 42 documentos.
"""

from sqlalchemy import select

from src.domain.documents.models.document import DocumentModel
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id

DENTRO = [
    "o que é o Web3 Bootcamp?",
    "quais programas existem no ecossistema?",
    "o que é o PSP?",
    "como funciona a mentoria BASE?",
    "quais são as entregáveis da mentoria PSP?",
    "o que é o BASE Gate?",
    "quando é a edição #02 do bootcamp?",
]
FORA = [
    "qual é o processo de renovação do PSP?",
    "como funciona o onboarding de novo mentorado?",
    "o que diz o SOP-GM-01 sobre transferência de ativos?",
    "qual a convenção de UTM para campanhas?",
    "como criar eventos no Discord?",
    "qual a capital da Austrália?",
    "como faço um bolo de cenoura?",
    "quem ganhou a copa de 2022?",
    "qual o melhor framework de frontend?",
]


def format_row(distance: float, question: str, title: str, threshold: float) -> str:
    veredito = "PASSA " if distance <= threshold else "RECUSA"
    return f"{veredito} {distance:.3f}  {question[:52]:<52} -> {title[:38]}"


class KnowledgeCalibrateCommand(Command):
    signature = "knowledge:calibrate"
    description = (
        "Mede a distância do melhor chunk para perguntas dentro e fora do escopo. "
        "Use para reconferir RAG_MAX_DISTANCE quando a base mudar de tamanho."
    )

    async def handle(self) -> None:
        limiar = settings.RAG_MAX_DISTANCE
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            print("NOTION_KB_ROOT_PAGE_ID não configurado — nada a calibrar.")
            return
        embeddings = get_embeddings_client()
        print(f"RAG_MAX_DISTANCE atual: {limiar}\n")

        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                for rotulo, perguntas in (("DENTRO", DENTRO), ("FORA", FORA)):
                    print(f"===== {rotulo} DO ESCOPO =====")
                    for pergunta in perguntas:
                        vetor = await embeddings.embed_query(pergunta)
                        distancia = DocumentChunkModel.embedding.cosine_distance(vetor)
                        stmt = (
                            select(distancia.label("d"), DocumentModel.title)
                            .join(
                                DocumentModel,
                                DocumentChunkModel.document_id == DocumentModel.uuid,
                            )
                            .where(
                                DocumentModel.status == "approved",
                                DocumentModel.deleted_at.is_(None),
                                DocumentModel.kb_root_page_id == root,
                            )
                            .order_by(distancia)
                            .limit(1)
                        )
                        linha = (await session.execute(stmt)).first()
                        if linha is None:
                            print(f"       ----  {pergunta[:52]:<52} -> (base vazia)")
                            continue
                        print(format_row(linha.d, pergunta, linha.title, limiar))
                    print()
            finally:
                CurrentAsyncSessionContext.clear()
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `DB_PORT=5434 uv run pytest tests/unit/app/console/test_knowledge_calibrate_command.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Rodar o comando de verdade**

Run: `uv run python cli.py knowledge:calibrate`
Expected: as 7 perguntas de DENTRO com `PASSA`; as 4 sem relação (Austrália, bolo, copa, framework) com `RECUSA`; Discord/SOP/UTM com `RECUSA`; renovação do PSP e onboarding com `PASSA` (são os casos da camada 2).

- [ ] **Step 6: Verificação de ponta a ponta pela API**

Subir a aplicação (`./start_dev`) e, em outro terminal:

```bash
curl -N -X POST http://localhost:8000/conversations/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"qual a capital da Austrália?"}'
```
Expected: eventos `token` formando "Não encontrei informações sobre isso na base de conhecimento." seguido da lista de temas, e um evento `sources` com `citations: []`.

```bash
curl -N -X POST http://localhost:8000/conversations/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"oi, tudo bem?"}'
```
Expected: saudação normal — **não** a recusa. Se vier recusa, a guarda da Task 8 está errada.

```bash
curl -N -X POST http://localhost:8000/conversations/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"o que é o Web3 Bootcamp?"}'
```
Expected: resposta real com citações.

- [ ] **Step 7: Rodar a suíte unitária inteira**

Run: `DB_PORT=5434 uv run pytest tests/unit -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/app/console/commands/knowledge_calibrate_command.py \
        tests/unit/app/console/
git commit -m "feat(kb): comando knowledge:calibrate para reconferir o limiar"
```

---

## Notas para quem executa

- **Não pule a Task 3.** Ela é operacional e não tem código, mas as Tasks 4, 5 e 6
  dependem de a procedência estar preenchida. Se o `SELECT` do Step 4 da Task 3
  não devolver `0`, pare e investigue antes de seguir.
- **Os 22 testes de integração que já falhavam continuam falhando** (banco de teste
  sem migrations). Compare sempre com `git stash` antes de culpar sua mudança.
- **A cópia da recusa aparece em dois lugares** (o serviço da Task 7 e o prompt da
  Task 9) e o teste da Task 9 amarra os dois pela constante importada. Se mudar o
  texto, mude na constante — o prompt tem a frase escrita à mão de propósito
  (o LLM precisa vê-la literal), e o teste garante que não divirjam.
