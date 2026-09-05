# Arquitetura do Projeto

Este documento descreve em detalhe a **arquitetura-alvo** do Oracle Borderless. Para regras operacionais condensadas, ver `CLAUDE.md`. Para decisões e racional, ver `docs/adr/`.

## Visão geral

A aplicação é uma API FastAPI que serve um **agente de IA (oráculo)**: consome uma base de conhecimento aprovada no **Notion via MCP** e responde perguntas em linguagem natural. O código é organizado em **três grandes regiões** com responsabilidades claras:

| Pasta | Responsabilidade | Pode importar de |
|---|---|---|
| `src/app/` | Pontos de entrada (HTTP, console, web) | `src/domain/`, `src/support/` |
| `src/domain/` | Negócio organizado por subdomínio | `src/support/` (apenas) |
| `src/support/` | Ferramental transversal (infra, integrações, utils) | só de si mesmo |

A regra de importação é **unidirecional**: `app` → `domain` → `support`. Quebra dessa direção é sinal de problema.

Três pilares definem esta arquitetura:

1. **Bounded contexts por subdomínio.** Cada subdomínio (`documents/`, `conversations/`, ...) é uma pasta autocontida em `src/domain/`. Mudanças locais não escorrem para o resto.
2. **Entity ≠ Model.** Entities são dataclasses puras de domínio; Models são SQLAlchemy de persistência. Um **Mapper** dedicado por subdomínio (`src/domain/{ctx}/mappers/`) faz a conversão; Repositórios delegam ao Mapper na fronteira pública. *(ADR-0003)*
3. **Actions são caso de uso, sem facade.** Cada Action vive em arquivo próprio com método `execute()`. Não existe Service agregador — Actions chamam outras Actions para compor. *(ADR-0004)*

> **Pontos em aberto** (a decidir em conjunto): interface (chat web vs. contexto de código), desenho interno do agente de IA, estratégia de ingestão/atualização da base de conhecimento, e a **autenticação** (haverá auth restrita ao ecossistema; mecanismo a definir). Não implemente auth concreta nem invente o desenho do agente antes da decisão.

## Estrutura completa

```
.
├── main.py                          # bootstrap: cria app, registra middlewares, lifespan
│
├── src/
│   ├── app/                         # ENTRADAS
│   │   ├── api/                     # HTTP/REST
│   │   │   ├── controllers/         # @staticmethod, finos
│   │   │   ├── requests/            # Pydantic de entrada
│   │   │   ├── responses/           # Pydantic de saída
│   │   │   ├── middlewares/         # RequestContext, DBSession, ProcessTime, ...
│   │   │   ├── dependencies/        # FastAPI Depends (ex.: futura auth)
│   │   │   ├── routes/              # APIRouter por subdomínio (autodiscovery)
│   │   │   └── exception_handlers.py
│   │   │
│   │   ├── console/                 # CLI + jobs
│   │   │   ├── commands/            # comandos CLI (Command pattern)
│   │   │   ├── jobs/                # subclasses de Job (sync do Notion, cleanup, ...)
│   │   │   └── schedule.py          # registra: schedule.call(MeuJob).cron(...)
│   │   │
│   │   └── web/                     # SSR opcional (não usado hoje)
│   │
│   ├── domain/                      # NEGÓCIO
│   │   ├── documents/               # base de conhecimento (docs aprovados do Notion)
│   │   │   ├── entities/            # @dataclass Document, DocumentStatus
│   │   │   ├── models/              # DocumentModel SQLAlchemy
│   │   │   ├── actions/             # IngestDocumentAction, ListDocumentsAction, ...
│   │   │   ├── services/            # Domain Services (raros)
│   │   │   ├── repositories/        # DocumentRepository (delega ao Mapper na fronteira)
│   │   │   ├── mappers/             # DocumentMapper — conversão Entity ↔ Model
│   │   │   ├── dtos/                # DocumentData, DocumentIngestData (cruzam camadas)
│   │   │   └── enums/               # enums por subdomínio (status, etc.)
│   │   │
│   │   ├── conversations/           # perguntas/respostas do oráculo
│   │   ├── observability/           # trace de cada turno (agent_traces) — ADR-0013
│   │   └── shared/                  # entities e VOs compartilhados
│   │       ├── entities/
│   │       └── value_objects/
│   │
│   └── support/                     # FERRAMENTAL TRANSVERSAL
│       ├── core/                    # infraestrutura fundamental
│       │   ├── lifespan.py          # LifespanManager
│       │   ├── settings.py          # Settings (pydantic-settings)
│       │   ├── database.py          # engines async + sync
│       │   ├── logging.py
│       │   ├── exceptions.py        # DomainError, ValidationError, NotFoundError, ...
│       │   ├── context/             # ContextVars
│       │   │   ├── current_request_context.py
│       │   │   ├── current_async_session_context.py
│       │   │   ├── current_db_session_context.py
│       │   │   └── background_task_context.py
│       │   ├── models/              # BaseModel, JobExecution, SeedExecution
│       │   ├── mixins/              # HasUUID, HasTimestamps, ApplyRelations
│       │   └── scheduling/          # Schedule, Job, JobScheduler + README
│       │
│       ├── clients/                 # integrações externas
│       │   ├── notion/              # NotionClient (base de conhecimento via MCP)
│       │   ├── embeddings/          # EmbeddingsClient (OpenAI text-embedding-3-small)
│       │   └── tavily/              # TavilyClient (web search com atribuição)
│       │
│       └── utils/                   # genéricos
│           └── notion_ids.py        # normalização de page id do Notion
│
├── database/                        # FORA de src/
│   ├── env.py                       # Alembic
│   ├── migrations/
│   ├── seeds/                       # idempotentes via seeds_executions
│   └── factories/                   # factory-boy para dev/test
│
├── docker/
└── docs/
```

## Por que três regiões e não duas

Pode parecer artificial separar `app/` (entradas) de `support/` (ferramental). A justificativa é o **modelo mental**:

- `app/` responde "como o mundo me alcança" — HTTP, CLI, web, eventualmente WebSocket para o chat.
- `domain/` responde "qual é o negócio" — vocabulário de quem usa (documentos, conversas, respostas).
- `support/` responde "como persisto, integro, configuro" — detalhes técnicos compartilhados (Notion/MCP, LLM, scheduler, database).

Misturar entrada com ferramental deixa a base difícil de navegar. Separar deixa `app/` minúsculo e focado, `support/` reusável e visível.

## A regra de dependência

```
   ┌──────────┐
   │   app    │    pode importar domain e support
   └────┬─────┘
        │
        ▼
   ┌──────────┐
   │  domain  │    pode importar support APENAS
   └────┬─────┘
        │
        ▼
   ┌──────────┐
   │ support  │    não importa nem app nem domain
   └──────────┘
```

**Implicações:**

- **Domain nunca importa FastAPI, request, response, controller.** Se uma Action precisa lançar erro, lança exceção de domínio (`src/support/core/exceptions.py`); o controller traduz para HTTPException.
- **Support não importa entidades de domínio.** Se um Client externo precisa de dados de um documento, recebe primitivos (`page_id: str`, `title: str`) — não a entidade.
- **Mixins e BaseModel ficam em support.** Mesmo sendo SQLAlchemy, são infraestrutura de persistência, não domínio.

## Anatomia de um subdomínio

Cada pasta em `src/domain/{contexto}/` segue a mesma estrutura. Vamos olhar `documents/` em detalhe:

```
src/domain/documents/
├── entities/
│   ├── __init__.py
│   └── document.py           # @dataclass Document
├── models/
│   ├── __init__.py
│   └── document.py           # class DocumentModel(BaseModel, HasUUID, ...)
├── actions/
│   ├── __init__.py
│   ├── ingest_document_action.py       # IngestDocumentAction
│   ├── update_document_action.py       # UpdateDocumentAction
│   ├── archive_document_action.py      # ArchiveDocumentAction
│   ├── get_document_action.py          # GetDocumentAction
│   ├── list_documents_action.py        # ListDocumentsAction
│   └── sync_from_notion_action.py      # SyncFromNotionAction
├── services/
│   └── (vazio normalmente — Domain Services são raros)
├── repositories/
│   ├── __init__.py
│   └── document_repository.py
├── mappers/
│   ├── __init__.py
│   └── document_mapper.py    # DocumentMapper — Entity ↔ Model
├── dtos/
│   ├── __init__.py
│   └── document_data.py      # @dataclass DocumentIngestData, DocumentUpdateData
└── enums/
    ├── __init__.py
    └── document_status_enum.py
```

### Entity (domínio puro)

```python
# src/domain/documents/entities/document.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Document:
    """Documento da base de conhecimento. Entidade de domínio pura."""
    uuid: UUID
    notion_page_id: str
    title: str
    content: str
    source_url: str
    status: str            # "approved" | "pending" | "archived"
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    def is_approved(self) -> bool:
        return self.status == "approved" and self.deleted_at is None

    def is_indexable(self) -> bool:
        """Só documentos aprovados entram na base consultável pelo oráculo."""
        return self.is_approved()
```

**Regras:**
- Sem `import sqlalchemy`, sem `import fastapi`, sem `import pydantic`.
- Pode ter métodos de negócio simples (`is_approved`, `is_indexable`).
- Use `@dataclass` puro ou `@dataclass(frozen=True)` se imutável.

### Model (persistência pura)

```python
# src/domain/documents/models/document.py
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.models.base_model import BaseModel
from src.support.core.mixins import HasUUID, HasTimestamps, ApplyRelations


class DocumentModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    __tablename__ = "documents"

    notion_page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(20), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

**Regras:**
- Sufixo **`Model`** no nome da classe — diferencia da Entity.
- Sem método de negócio. Apenas mapeamento.
- Mixins padrão: `BaseModel, HasUUID, HasTimestamps, ApplyRelations`.

### Mapper (Entity ↔ Model)

```python
# src/domain/documents/mappers/document_mapper.py
from src.domain.documents.entities.document import Document


class DocumentMapper:
    @staticmethod
    def to_entity(model: "DocumentModel") -> Document:
        return Document(
            uuid=model.uuid,
            notion_page_id=model.notion_page_id,
            title=model.title,
            content=model.content,
            source_url=model.source_url,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    @staticmethod
    def to_model_attrs(entity: Document) -> dict:
        return {
            "uuid": entity.uuid,
            "notion_page_id": entity.notion_page_id,
            "title": entity.title,
            "content": entity.content,
            "source_url": entity.source_url,
            "status": entity.status,
        }
```

**Regras:**
- Sufixo **`Mapper`**.
- Métodos `@staticmethod` — sem estado.
- `to_entity(model) -> Entity`. Para escrita, `to_model_attrs(entity) -> dict` (passado a `Model(**attrs)` ou a `update().values(**attrs)`).
- Mapper pode importar Mapper de outro subdomínio quando um relacionamento exige. A direção segue ADR-0001 (`app → domain → support`).

### Repository (a ponte)

```python
# src/domain/documents/repositories/document_repository.py
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from src.support.core.context import CurrentAsyncSessionContext
from src.domain.documents.entities.document import Document
from src.domain.documents.mappers import DocumentMapper
from src.domain.documents.models.document import DocumentModel


class DocumentRepository:
    def __init__(self):
        self.session = CurrentAsyncSessionContext.get()
        if not self.session:
            raise RuntimeError("No active database session found in context.")

    async def get_by_id(self, document_id: UUID, with_trashed: bool = False) -> Optional[Document]:
        query = select(DocumentModel).where(DocumentModel.uuid == document_id)
        if not with_trashed:
            query = query.where(DocumentModel.deleted_at.is_(None))

        result = await self.session.execute(query)
        model = result.unique().scalar_one_or_none()
        return DocumentMapper.to_entity(model) if model else None

    async def get_by_notion_page_id(self, page_id: str) -> Optional[Document]:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.notion_page_id == page_id)
        )
        model = result.unique().scalar_one_or_none()
        return DocumentMapper.to_entity(model) if model else None

    async def list_documents(self, skip: int = 0, limit: int = 100) -> list[Document]:
        query = (
            select(DocumentModel)
            .where(DocumentModel.deleted_at.is_(None))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [DocumentMapper.to_entity(m) for m in result.unique().scalars().all()]

    async def create(self, document: Document) -> Document:
        model = DocumentModel(**DocumentMapper.to_model_attrs(document))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return DocumentMapper.to_entity(model)
```

**Regras:**
- Pega session do contexto.
- API pública fala em **Entities** (Document), não Models.
- **Conversão Entity ↔ Model fica no Mapper**, não inline no Repository.
- Não comita — middleware faz isso.

### Action (caso de uso)

```python
# src/domain/documents/actions/ingest_document_action.py
from src.domain.documents.entities.document import Document
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.domain.documents.dtos.document_data import DocumentIngestData
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.exceptions import DomainConflictError, ValidationError


class IngestDocumentAction:
    """Ingere um documento aprovado do Notion na base de conhecimento."""

    def __init__(self, notion_client: NotionClient):
        self.repository = DocumentRepository()
        self.notion = notion_client

    async def execute(self, data: DocumentIngestData) -> Document:
        page = await self.notion.get_page(data.notion_page_id)

        if not page.is_approved:
            raise ValidationError("Documento não está aprovado — não pode ser ingerido")

        existing = await self.repository.get_by_notion_page_id(data.notion_page_id)
        if existing:
            raise DomainConflictError(f"Documento {data.notion_page_id} já foi ingerido")

        document = Document(
            uuid=None,     # gerado pelo HasUUID no insert
            notion_page_id=page.id,
            title=page.title,
            content=page.content,
            source_url=page.url,
            status="approved",
            created_at=None,
            updated_at=None,
        )
        return await self.repository.create(document)
```

**Regras:**
- Sufixo **`Action`** no nome.
- Método público único: **`execute()`**.
- Recebe **DTOs** ou primitivos, retorna **Entity**.
- Lança **exceções de domínio** (não `HTTPException` — quem traduz é o controller).
- Helpers privados com `_`.

### Controller (fino)

```python
# src/app/api/controllers/document_controller.py
from fastapi import Request

from src.app.api.requests.document_requests import IngestDocumentRequest
from src.app.api.responses.document_responses import DocumentResponse
from src.support.clients.notion.notion_client import NotionClient
from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.dtos.document_data import DocumentIngestData


class DocumentController:
    @staticmethod
    async def ingest_document(request: Request, payload: IngestDocumentRequest):
        action = IngestDocumentAction(notion_client=NotionClient())

        document = await action.execute(DocumentIngestData(
            notion_page_id=payload.notion_page_id,
        ))

        return DocumentResponse.from_entity(document)
```

**Regras:**
- `@staticmethod`.
- Não chama Repository diretamente — só Action.
- Não tem regra de negócio.
- Converte payload em DTO, chama Action, devolve Response.

### Rota (autodescoberta)

```python
# src/app/api/routes/documents.py
from fastapi import APIRouter

from src.app.api.controllers.document_controller import DocumentController


router = APIRouter(prefix="/documents", tags=["Documents"])
# Auth: ponto em aberto. Quando definida, entra como dependency do router:
#   router = APIRouter(..., dependencies=[Depends(require_authenticated)])

router.get("")(DocumentController.list_documents)
router.post("")(DocumentController.ingest_document)
router.get("/{document_id}")(DocumentController.get_document)
router.put("/{document_id}")(DocumentController.update_document)
router.delete("/{document_id}")(DocumentController.archive_document)
```

`src/app/api/routes/__init__.py` faz autodiscovery via `pkgutil.iter_modules` — não precisa registrar nada manualmente.

## Componentes transversais em `src/support/`

### Sessão DB via ContextVar (`src/support/core/context/`)

`DBSessionMiddleware` abre sessão async (e factory de sync lazy) por request, popula `CurrentAsyncSessionContext` e `CurrentSessionContext`, comita/rollback no final. Repositórios acessam via `CurrentAsyncSessionContext.get()` — sem injeção por parâmetro.

Detalhes: **ADR-0006**.

### Request context (`src/support/core/context/`)

`CurrentRequestContext` mantém request e (quando a auth existir) o usuário da request atual. Acesso de qualquer lugar:

```python
request = CurrentRequestContext.get_request()
```

### Integração com Notion via MCP (`src/support/clients/notion/`)

A base de conhecimento vem do **Notion através do MCP (Model Context Protocol)**. O `NotionClient` encapsula essa integração e expõe apenas o necessário ao domínio (buscar página, listar páginas aprovadas). **Só conteúdo aprovado/liberado é consumido** — nenhum documento restrito entra na base.

```python
# src/support/clients/notion/notion_client.py
class NotionClient:
    async def get_page(self, page_id: str) -> NotionPage: ...
    async def list_approved_pages(self) -> list[NotionPage]: ...
```

O desenho fino da ingestão (full sync vs. incremental, embeddings, cache) é **ponto em aberto** — ver seção de decisões pendentes.

### LLM: Claude ou GPT (`src/support/agent/`)

O oráculo pode usar **Claude (Anthropic)** ou **GPT (OpenAI)**. O provedor é escolhido em runtime pela variável `LLM_PROVIDER` (`anthropic` | `openai`), sem mudar código de domínio.

Não existe client HTTP de LLM próprio: o único acesso ao modelo é via um `StateGraph` **LangGraph** (ADR-0016), inteiramente contido em `src/support/agent/graph/`:

```
                  ┌─────────┐
        START ───►│  gate   │  modelo pequeno, structured output, fail-open
                  └────┬────┘
                       │ should_retrieve
              ┌────────┴────────┐
       retrieve=false      retrieve=true
              │                 │
              │            ┌────▼─────┐
              │            │ retrieve │  pgvector top-k + limiar
              │            └────┬─────┘
              │                 │ has_grounding
              │        ┌────────┴────────┐
              │   vazio & !degraded    tem contexto
              │        │                 │
              │   ┌────▼────┐            │
              │   │ refuse  │            │
              │   └────┬────┘            │
              │        │                 │
              └────────┼─────────────►┌──▼─────┐
                       │              │ answer │◄──┐
                       │              └──┬─────┘   │
                       │      tools_condition│     │
                       │              ┌──────┴───┐ │
                       │              │  tools   │─┘
                       ▼              └──────────┘
                      END ◄───────────────┘
```

```
src/support/agent/
├── ports.py              # TurnDependencies, TurnGraphPort — fronteira com o domínio
├── models.py             # seleção de provider (Claude/GPT) num ponto único
├── tools.py              # WebSearchTool / FetchNotionTool (HTTP-only, por decisão)
└── graph/
    ├── state.py           # TurnState
    ├── nodes.py           # gate · retrieve · refuse · answer
    ├── edges.py           # should_retrieve · has_grounding (funções puras)
    ├── builder.py         # build_turn_graph() — compilado uma vez no módulo, sem checkpointer
    └── runner.py          # TurnGraphRunner — implementa TurnGraphPort
```

O domínio consome o grafo por um único Protocol fino, `TurnGraphPort` (`src/support/agent/ports.py`) — nunca importa `langgraph` nem `langchain*`. A fronteira é protegida por `tests/unit/support/agent/test_domain_boundary.py`. Na direção oposta, os nós do grafo recebem as Actions de domínio (`SearchKnowledgeBaseAction`, `ListKnowledgeSectionsAction`, `build_out_of_scope_reply`) injetadas via `TurnDependencies`, sem que `support/` importe `domain/`.

**Consumo em duas fases, ambas no corpo SSE (ADR-0020).** `TurnGraphPort.run()` é síncrono e devolve um `TurnRun`. O controller abre `async_session_scope()` (`src/support/core/session_scope.py`) dentro do corpo do `StreamingResponse`, constrói os `deps` ali via `RunTurnAction` e consome `prelude()` — gate → retrieve → (refuse | entrada do nó `answer`) — até o fim; depois fecha o escopo e consome `stream()` sem sessão. O corte é a **entrada real** do nó `answer`, sinalizada pelo evento `task` do `stream_mode="debug"` (não o primeiro token: uma resposta que abre só com `tool_calls` não produz token nenhum, e o laço `answer -> tools -> answer` rodaria com a conexão de banco presa). Do payload `debug` o runner lê só `type` e `payload.name`. Ver **ADR-0016** (por que duas fases) e **ADR-0020** (por que no corpo, e o critério de corte).

**Contrato de saída: AG-UI (ADR-0019).** O que sai do runner não é texto cru: é uma união de dataclasses (`TextChunk`, `SourcesChunk`, `StepChunk`, `ToolCall*Chunk`, em `src/support/agent/ports.py`) que um `TurnEmitter` sintetiza a partir dos `debug` (`task` = entrada do nó → `started`), dos `updates` (um passo por nó; `ToolMessage` vira result só com status) e dos `messages` (texto e `tool_call_chunks` do nó `answer`). A tradução para eventos do protocolo AG-UI — `RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`, `TEXT_MESSAGE_*`, `CUSTOM oracle.step`/`oracle.sources`, `RUN_FINISHED`/`RUN_ERROR` — mora em `src/app/api/streaming/ag_ui_encoder.py`, na camada `app`; o body do endpoint é o `RunAgentInput` (`src/app/api/requests/run_agent_request.py`). Domínio e grafo não importam `ag_ui` (teste de fronteira). Com a fase 1 no corpo (ADR-0020), `RUN_STARTED` é o primeiro byte e cada passo chega ao vivo.

Não há checkpointer: o histórico da conversa segue exclusivamente em `conversations`/`messages`, decisão mantida do ADR-0007 e reafirmada no ADR-0016.

Modelos e chaves por provedor vêm das settings: `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_SMALL_MODEL` e `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_SMALL_MODEL`, resolvidos em `src/support/agent/models.py`.

**LangSmith:** tracing fino (spans, prompts, I/O de tool, tokens, custo, replay) é enviado ao LangSmith quando `LANGSMITH_TRACING=true`, configurável via `LANGSMITH_API_KEY`/`LANGSMITH_PROJECT` nas settings. `agent_traces` (Postgres) mantém as colunas planas agregáveis (decisão do gate, outcome, distância do retrieval, latências) — não é redundância acidental, é o que viabiliza `GROUP BY` na página de Ops, que o LangSmith não pode calcular. `user_email` só chega ao LangSmith como hash estável; o e-mail em claro fica só em `agent_traces`.

### Scheduler distribuído (`src/support/core/scheduling/`)

Sistema Laravel-like com DSL fluente. No oráculo, o uso principal é **sincronizar a base de conhecimento do Notion** periodicamente:

```python
# src/app/console/schedule.py
schedule.call(SyncKnowledgeBaseJob).hourly()
schedule.call(CleanupConversationsJob).daily(hour=3)
```

Coordenação distribuída via PostgreSQL advisory locks + tabela `job_executions`. Seguro em múltiplas réplicas. Documentação completa em `src/support/core/scheduling/README.md`.

### Lifespan (`src/support/core/lifespan.py`)

`LifespanManager` centraliza startup/shutdown: warmup do pool de DB, warmup de clients externos (Notion/MCP), boot do scheduler.

### Dual engine SQLAlchemy

Async (asyncpg, padrão) + sync (psycopg, para o jobstore do APScheduler e scripts). Configurados em `src/support/core/database.py`.

## Fluxo de uma request HTTP

```
Cliente
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ main.py — middlewares (ordem):                              │
│   1. RequestContextMiddleware  (Request em ContextVar)      │
│   2. DBSessionMiddleware       (sessão async + sync lazy)   │
│   3. BackgroundTaskMiddleware  (BackgroundTasks pronto)     │
│   4. ProcessTimeMiddleware     (header X-Process-Time)      │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ src/app/api/routes/{contexto}.py — APIRouter                │
│   dependencies=[ ... ]   (auth: ponto em aberto)            │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ src/app/api/controllers/{contexto}_controller.py            │
│   - extrai payload                                          │
│   - constrói DTO                                            │
│   - instancia Action                                        │
│   - chama action.execute(dto)                               │
│   - converte Entity → Response                              │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ src/domain/{contexto}/actions/{verbo}_{subst}_action.py     │
│   - regra de negócio                                        │
│   - chama Repository(s) e Client(s) externos                │
│   - lança exceções de domínio                               │
│   - retorna Entity                                          │
└─────────────────────────────────────────────────────────────┘
   │
   ├──► src/domain/{contexto}/repositories/
   │       - session de CurrentAsyncSessionContext.get()
   │       - query SQLAlchemy
   │       - converte Model → Entity (via Mapper), retorna
   │
   └──► src/support/clients/  (notion/MCP, llm, ...)
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ src/app/api/responses/{contexto}_responses.py               │
│   DocumentResponse.from_entity(document)                    │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
JSON response — DBSessionMiddleware faz commit
```

## Tratamento de exceções

A arquitetura separa exceções de domínio das de transporte:

### Exceções de domínio (`src/support/core/exceptions.py`)

```python
class DomainError(Exception):
    """Base para todas as exceções de domínio"""

class NotFoundError(DomainError):
    """Recurso não encontrado"""

class DomainConflictError(DomainError):
    """Conflito de regra de negócio (ex: documento já ingerido)"""

class ValidationError(DomainError):
    """Falha de validação de regra"""

class UnauthorizedDomainError(DomainError):
    """Operação não permitida pelo domínio"""
```

### Tradução para HTTP

`src/app/api/exception_handlers.py` registra handlers que convertem exceções de domínio em HTTP:

```python
@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})

@app.exception_handler(DomainConflictError)
async def conflict_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

**Por que não lançar `HTTPException` em Action:** Actions devem ser reutilizáveis em jobs, CLI e (futuramente) consumers — onde HTTPException não faz sentido. A separação preserva essa portabilidade.

## Console e jobs

```
src/app/console/
├── commands/                    # comandos CLI (Command pattern)
│   ├── __init__.py
│   ├── seed_command.py          # python cli.py db:seed
│   └── documents_ingest_command.py
├── jobs/                        # subclasses de Job
│   ├── __init__.py
│   ├── sync_knowledge_base_job.py
│   └── cleanup_conversations_job.py
└── schedule.py                  # registra jobs no scheduler
```

`schedule.py`:

```python
from src.support.core.scheduling import Schedule
from src.app.console.jobs.sync_knowledge_base_job import SyncKnowledgeBaseJob
from src.app.console.jobs.cleanup_conversations_job import CleanupConversationsJob

schedule = Schedule()
schedule.call(SyncKnowledgeBaseJob).hourly()
schedule.call(CleanupConversationsJob).daily(hour=3)
```

`LifespanManager` carrega esse `schedule.py` no startup automaticamente.

## Trace do turno

Cada turno do oráculo acumula seu próprio rastro num coletor em memória — `TurnTraceDraft`, em `src/domain/observability/dtos/` — que a `OpenTurnAction` preenche com recência; gate, retrieval, recusa e a fase do engine (primeiro token, duração, tokens, tool calls) chegam pelos `TurnSignals` que o grafo escreve e que o gerador SSE do controller apenas absorve.

Terminado o stream, a **mesma** background task que persiste a resposta do assistente grava o trace numa linha de `agent_traces`, em sessão própria (`run_in_async_session`) — o trace primeiro, porque turno que quebrou é o que mais interessa. Nada disso pode derrubar um turno: o call site fica sob `try/except` que loga e engole.

A leitura é agregada em SQL e servida pelos quatro endpoints só-leitura de `/ops`, consumidos pela página `/ops` do frontend. Racional completo em [ADR-0013](adr/0013-trace-por-turno-no-postgres.md).

## Interface web

A interface é uma **SPA React + Vite** em [`frontend/`](../frontend/), fora de `src/` e com toolchain própria. Ela fala com o backend só por HTTP/SSE — não há SSR nem template servido pelo FastAPI. A UI mínima em HTML puro do M1 (`src/app/web/index.html` + `routes/web.py`) foi removida quando o front React entrou em uso.

Servir o `frontend/dist` em produção (static do FastAPI ou host dedicado) é decisão de deploy, ainda aberta.

## Quando reconsiderar a arquitetura

Sinais de que a estrutura precisa evoluir:

- **Crescimento extremo de subdomínios** com pouca interação → considerar quebra em serviços separados.
- **O agente de IA ganha complexidade própria** (roteamento de ferramentas, múltiplas fontes além do Notion) → considerar um subdomínio `agent/` dedicado com Actions e Services específicos.
- **Necessidade de versionar API** (v1, v2 paralelas) → adicionar `src/app/api/v1/`, `src/app/api/v2/`.

Mudanças desse porte exigem **ADR antes** da implementação.

## Referências internas

- Distinção Action vs Service: `docs/actions-vs-services.md`
- Naming e padrões: `docs/conventions.md`
- Adicionar subdomínio: `docs/adding-new-domain.md`
- Database (dual engine, seeds, factories): `docs/database-guide.md`
- Testes com context vars: `docs/testing-guide.md`
- Scheduler: `src/support/core/scheduling/README.md`
- Decisões arquiteturais: `docs/adr/`
