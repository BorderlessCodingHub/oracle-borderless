# CLAUDE.md

Este arquivo descreve a arquitetura do projeto: padrão Spatie Laravel Beyond CRUD adaptado ao FastAPI.

## Visão geral do projeto

**Oracle Borderless** é um **agente de IA no estilo "Claude Code" reposicionado como oráculo**: uma *single source of truth* consultável em linguagem natural. Qualquer pessoa faz uma pergunta em linguagem natural e recebe uma resposta útil, confiável e amigável, baseada **exclusivamente em fontes aprovadas**.

- A base de conhecimento vem do **Notion via MCP (Model Context Protocol)** — apenas documentos liberados.
- O agente responde sobre **regras de negócio do ecossistema** e **dados operacionais** (ex.: resultados de alunos), sempre em linguagem clara.
- **Nada confidencial** entra na base ou é exposto; o conteúdo vem só de fontes/documentos permitidos pelas restrições de acesso do MCP do Notion.
- O projeto vai para **produção com URL/domínio próprio e aparência de produto**.

A API é FastAPI, reorganizada em três camadas claras: **`src/app/`** (pontos de entrada), **`src/domain/`** (negócio organizado por subdomínio), **`src/support/`** (ferramental transversal). A arquitetura tem três pilares que a diferenciam de um scaffold FastAPI típico:

1. **Bounded contexts por subdomínio.** Cada subdomínio (`documents/`, `conversations/`, `users/`, ...) é uma pasta autocontida em `src/domain/` com suas Entities, Models, Actions, Services, Repositories e DTOs. Mudanças em um subdomínio não escorrem para os outros.
2. **Entity ≠ Model.** Entities são dataclasses puras de domínio (`src/domain/{ctx}/entities/`); Models são SQLAlchemy de persistência (`src/domain/{ctx}/models/`). Repositórios traduzem entre os dois via Mapper.
3. **Actions são caso de uso, sem facade.** `src/domain/{ctx}/actions/` contém uma Action por arquivo, classe terminada em `Action`, método `execute()`. Não há Service agregador — Actions chamam outras Actions quando precisam compor.

Componentes transversais (scheduler distribuído, ContextVars de request, dual engine SQLAlchemy, integração com Notion via MCP) ficam em `src/support/` e são consumidos por todo o domínio.

Para arquitetura completa, leia **`docs/architecture.md`**.

> **Pontos ainda em aberto** (a decidir em conjunto, não inventar): interface (chat web vs. contexto de código), arquitetura interna do agente de IA, estratégia de ingestão/atualização da base de conhecimento. Enquanto não decidido, não invente o desenho do agente.

## Stack principal

- **Framework:** FastAPI (Python 3.13+)
- **ORM:** SQLAlchemy 2.0 async (`asyncpg`) + sync (`psycopg`) paralelos
- **Migrations:** Alembic (diretório `database/migrations/`)
- **Validação:** Pydantic v2 + `pydantic-settings`
- **Base de conhecimento:** Notion via **MCP (Model Context Protocol)** — client em `src/support/clients/notion/`. Só consome documentos aprovados/liberados.
- **LLM:** o oráculo pode usar **Claude (Anthropic)** ou **GPT (OpenAI)**, selecionável via `LLM_PROVIDER` (`anthropic` | `openai`). O acesso ao modelo é **exclusivamente** pelo LangGraph dentro de `src/support/agent/graph/` (`nodes.py` contém o gate e a resposta; `models.py` seleciona o provedor) — não há client HTTP próprio de LLM. Ver ADR-0016.
- **Agente de IA:** um `StateGraph` LangGraph (gate → retrieve → refuse/answer + tool loop) orquestra Claude ou GPT sobre a base de conhecimento, consumido em dois escopos de sessão via `TurnGraphPort.run()` (`prelude()` no corpo SSE dentro de `async_session_scope()`, `stream()` sem sessão). O `input` do turno carrega `mode` (`chat`/`navigate`) e `locale` (`en`/`pt-BR`); em `mode=navigate` o gate é pulado e a intenção é `navigate` direto. Quando o modelo chama `navigate_platform`, a aresta `after_answer` desvia para um nó próprio, `navigate` (`src/support/agent/graph/navigate_node.py`) — não para o `ToolNode` —, que resolve o destino na `borderless-api` e escreve `navigation` no state antes da frase final. Navegar é capacidade da **sessão**, não do endpoint: só sessões `platform_bearer` (chat embutido na Platform) recebem a tool `navigate_platform`, o bloco de prompt de navegação e a busca do catálogo — o SPA do oráculo, que não executa redirect, fica só com `web_search`/`fetch_notion_page`. Observabilidade fina no LangSmith; `agent_traces` mantém as colunas agregáveis. Ver **ADR-0016**, **ADR-0020** e **ADR-0022**.
- **Protocolo de UI:** o turno é entregue ao cliente como **`StreamEvent`s do LangChain** (`astream_events`, `version="v2"`, `stream_mode=["values","updates"]`) sobre SSE: `POST /conversations/ask` recebe `{"input": {"question"}, "config": {"run_id", "configurable": {"thread_id"}}}` e responde blocos `event: <nome>\ndata: <StreamEvent JSON>` — `on_chain_start` do raiz → `on_chain_start/end` dos nós, `on_chain_stream` (`updates`/`values`), `on_chat_model_stream`, `on_tool_start/end` → `on_chain_end` do raiz (ou `on_chain_error`). O runner **redige** cada evento (allowlist + projeção do state, regra 4) antes de cruzar o port como `GraphEvent`; a serialização mora em `src/app/api/streaming/`. **Domínio e grafo não conhecem o fio.** Ver ADR-0021.
- **Autenticação:** plataforma Borderless como IdP via **BFF**: `POST /auth/login` (público, sem key) chama o signin da plataforma, guarda o `accessToken` **opaco** na tabela `sessions` e devolve cookie httpOnly `ob_session`; `require_user` resolve cookie → sessão → valida na plataforma (`GET /api/users/profile`, cache 60s, fail-open ≤10min); `GET /auth/me` restaura, `POST /auth/logout` revoga. Admin do `/ops` por allowlist `ADMIN_EMAILS` (404 para os demais). O proxy da Platform usa um segundo caminho: `require_user` lê `Authorization: Bearer <token>` antes do cookie e resolve via `ResolveBearerAction`, que faz find-or-create na mesma tabela `sessions` (`source="platform_bearer"`, chaveada pelo hash do token) e depois segue o mesmo cache/fail-open de `ResolveSessionAction`. **Não há Keycloak/OpenFGA/Supabase nem JWT neste projeto.** Ver ADR-0017, ADR-0018, ADR-0022 e `docs/autenticacao.md`.
- **Scheduler:** APScheduler com jobstore PostgreSQL (`src/support/core/scheduling/`) — usado, entre outros, para jobs de sincronização da base de conhecimento.
- **PK padrão:** UUID v7 (`uuid6.uuid7`) via mixin `HasUUID`
- **Package manager:** UV

## Estrutura de pastas (alvo)

```
.
├── main.py                          # bootstrap mínimo: app FastAPI + middlewares + handlers
│
├── src/
│   ├── app/                         # como o mundo entra na aplicação
│   │   ├── api/                     # HTTP/REST
│   │   │   ├── controllers/         # @staticmethod handlers, finos
│   │   │   ├── requests/            # schemas Pydantic de entrada
│   │   │   ├── responses/           # schemas Pydantic de saída
│   │   │   ├── middlewares/         # DBSession, RequestContext, ProcessTime, ...
│   │   │   ├── dependencies/        # FastAPI Depends (ex.: futura auth)
│   │   │   ├── routes/              # APIRouter por subdomínio (autodiscovery)
│   │   │   └── exception_handlers.py
│   │   │
│   │   └── console/                 # CLI + jobs agendados
│   │       ├── commands/            # comandos CLI — Command subclasses (auto-discovered by cli.py)
│   │       ├── jobs/                # subclasses de Job (scheduled tasks, ex.: sync do Notion)
│   │       └── schedule.py          # registro: schedule.call(MeuJob).daily()
│   │
│   ├── domain/                      # o que é o negócio
│   │   ├── documents/               # subdomínio: base de conhecimento (docs do Notion)
│   │   │   ├── entities/            # @dataclass Document — domínio puro
│   │   │   ├── models/              # Document SQLAlchemy — persistência pura
│   │   │   ├── actions/             # IngestDocumentAction, ListDocumentsAction, ...
│   │   │   ├── services/            # Domain Services (raros, regra ampla)
│   │   │   ├── repositories/        # DocumentRepository — fala em Entities, persiste Models
│   │   │   ├── mappers/             # DocumentMapper — conversão Entity ↔ Model
│   │   │   ├── dtos/                # DTOs internos do subdomínio (DocumentData, ...)
│   │   │   └── enums/               # DocumentStatusEnum, etc.
│   │   ├── conversations/           # mesmo formato (perguntas/respostas do oráculo)
│   │   └── shared/                  # entities/value objects compartilhados
│   │
│   └── support/                     # ferramental transversal
│       ├── core/                    # infra fundamental
│       │   ├── lifespan.py          # LifespanManager (warmup, scheduler boot)
│       │   ├── settings.py          # Settings (pydantic-settings)
│       │   ├── database.py          # engines async+sync
│       │   ├── logging.py
│       │   ├── exceptions.py        # exceções de domínio base
│       │   ├── context/             # ContextVars (request, sessão, bg tasks)
│       │   ├── models/              # BaseModel, JobExecution, SeedExecution
│       │   ├── mixins/              # HasUUID, HasTimestamps, ApplyRelations
│       │   └── scheduling/          # Schedule, Job, JobScheduler
│       ├── clients/                 # integrações externas (notion/MCP, embeddings, tavily)
│       └── utils/                   # utilitários genéricos (notion_ids, ...)
│
├── database/                        # FORA de src/
│   ├── migrations/                  # Alembic
│   ├── seeds/                       # dados essenciais para prod (com tracking)
│   └── factories/                   # factory-boy para dev/test
│
├── docker/
└── docs/                            # documentação arquitetural
```

## Padrão de Actions — sem Service facade

**Decisão importante:** o padrão Spatie estrito **não tem** Service agregador. Toda regra de caso de uso vira uma Action, e Actions chamam outras Actions quando precisam compor.

| Caminho | Tipo | Exemplo |
|---|---|---|
| `src/domain/{ctx}/actions/{verbo}_{substantivo}_action.py` | **Action** | `IngestDocumentAction.execute(...)` |
| `src/domain/{ctx}/services/{nome}_service.py` | **Domain Service** | `RelevanceScorer`, `ContentSanitizer` |
| `src/support/clients/notion/notion_client.py` | **Client** (integração externa via MCP) | `NotionClient.list_approved_pages(...)` |

**Ao criar código novo:**
- Caso de uso (ingerir documento, responder pergunta, listar…) → **Action** em `src/domain/{ctx}/actions/`.
- Lógica de domínio sem dono natural (cálculo, validador complexo, regra ampla) → **Domain Service**.
- Integração externa (HTTP, MCP, LLM, fila) → **Client** em `src/support/clients/`.
- Composição de várias Actions → **Action que chama outras Actions**, não Service.

Leia **`docs/actions-vs-services.md`** para a árvore de decisão completa com exemplos.

## Regras inegociáveis

Violar qualquer uma destas regras quebra premissas do sistema. Pergunte antes de infringir.

1. **Domain não importa infraestrutura.** Arquivos em `src/domain/{ctx}/entities/` não podem importar `sqlalchemy`, `fastapi`, `pydantic`. Models, Actions e Services podem importar SQLAlchemy mas continuam proibidos de importar HTTP. *(ver ADR-0003)*

2. **Entity é dataclass pura. Model é SQLAlchemy.** Nunca misture. A conversão Entity ↔ Model é responsabilidade do **Mapper** do subdomínio (`src/domain/{ctx}/mappers/{nome}_mapper.py`) — não inline no Repository. Repositórios delegam ao Mapper na fronteira pública. Actions trabalham com Entities. *(ver ADR-0003)*

3. **Sessão de banco vem do contexto, não é criada manualmente.** Repositórios acessam via `CurrentAsyncSessionContext.get()`. O `DBSessionMiddleware` já abriu, comita e fecha a sessão por request. Criar `AsyncSessionLocal()` em controller, action ou repository é sinal de erro. Fora do request (corpo SSE, jobs, eval) o escopo vem de `src/support/core/session_scope.py` (`async_session_scope` / `run_in_async_session`), aberto por `app`/`console`/`evals` — nunca pelo domínio (`test_domain_boundary.py` falha se `src/domain/` importar `AsyncSessionLocal` ou `session_scope`). *(ver ADR-0006 e ADR-0020)*

4. **Nada confidencial na base de conhecimento.** O oráculo só responde a partir de fontes/documentos aprovados e liberados pelo MCP do Notion. Nenhum conteúdo restrito pode ser ingerido, persistido ou exposto nas respostas.

5. **Controllers são finos.** Recebem request, extraem dados, chamam **uma** Action, retornam Response schema. Sem regra de negócio, sem orquestração. Composição é responsabilidade de Action.

6. **Sem Service agregador.** Cada caso de uso é uma Action separada. Para compor, uma Action chama outra. Domain Services existem só para lógica realmente sem dono (raros).

7. **Schemas Pydantic ficam em `src/app/api/`.** Requests, responses, dependency schemas. **DTOs internos** (que cruzam camadas dentro do domínio) ficam em `src/domain/{ctx}/dtos/` — geralmente dataclasses, não Pydantic.

8. **Jobs devem ser idempotentes.** O `Job.execute()` em `src/support/core/scheduling/job.py` aplica advisory lock + deduplicação via tabela `job_executions`, mas a lógica em `action()` precisa tolerar re-execução. Especialmente relevante para jobs de sincronização da base de conhecimento.

9. **Seeds com tracking.** Toda seed nova deve estar registrada em `database/seeds/__init__.py`. A tabela `seeds_executions` previne re-execução — não tente contornar.

10. **Não introduza dependências novas sem discussão.** Stack é definida no `pyproject.toml`.

## Convenções principais

### Entity vs Model

```python
# src/domain/documents/entities/document.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

@dataclass
class Document:
    """Entidade de domínio. Pura. Sem SQLAlchemy."""
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
```

```python
# src/domain/documents/models/document.py
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.models.base_model import BaseModel
from src.support.core.mixins import HasUUID, HasTimestamps, ApplyRelations

class DocumentModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    """Model de persistência. Apenas mapeamento — sem regra de negócio."""
    __tablename__ = "documents"
    notion_page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(20), index=True)
```

### Actions

```python
# src/domain/documents/actions/ingest_document_action.py
from src.domain.documents.entities.document import Document
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.clients.notion.notion_client import NotionClient

class IngestDocumentAction:
    """Ingere um documento aprovado do Notion na base de conhecimento."""

    def __init__(self, notion_client: NotionClient):
        self.repository = DocumentRepository()
        self.notion = notion_client

    async def execute(self, notion_page_id: str) -> Document:
        # buscar página no Notion, validar que é aprovada, persistir, retornar Entity
        ...
```

### Repositories

Trabalham na fronteira: recebem Entities, devolvem Entities, mas internamente usam Models SQLAlchemy. A conversão Entity ↔ Model fica num **Mapper** dedicado (`src/domain/{ctx}/mappers/{nome}_mapper.py`) — não inline.

```python
# src/domain/documents/mappers/document_mapper.py
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

```python
# src/domain/documents/repositories/document_repository.py
from src.domain.documents.mappers import DocumentMapper

class DocumentRepository:
    def __init__(self):
        self.session = CurrentAsyncSessionContext.get()

    async def get_by_id(self, document_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(DocumentModel).where(DocumentModel.uuid == document_id)
        )
        model = result.unique().scalar_one_or_none()
        return DocumentMapper.to_entity(model) if model else None

    async def create(self, document: Document) -> Document:
        model = DocumentModel(**DocumentMapper.to_model_attrs(document))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return DocumentMapper.to_entity(model)
```

### Controllers

```python
# src/app/api/controllers/document_controller.py
class DocumentController:
    @staticmethod
    async def ingest_document(request: Request, data: IngestDocumentRequest):
        notion = NotionClient()
        action = IngestDocumentAction(notion_client=notion)
        document = await action.execute(notion_page_id=data.notion_page_id)
        return DocumentResponse.from_entity(document)
```

### Rotas

`src/app/api/routes/__init__.py` faz **autodiscovery** via `pkgutil.iter_modules`. Basta criar `src/app/api/routes/meu_dominio.py` com `router = APIRouter(...)` (ou `public_router` para sem auth) e está registrado.

```python
# src/app/api/routes/documents.py
router = APIRouter(prefix="/documents", tags=["Documents"])
# Rota de negócio nasce com require_user (ADR-0017); public_router é exceção deliberada.
router.post("")(DocumentController.ingest_document)
router.get("")(DocumentController.list_documents)
```

### Jobs

```python
# src/app/console/jobs/sync_knowledge_base_job.py
from src.support.core.scheduling import Job

class SyncKnowledgeBaseJob(Job):
    async def action(self):
        # idempotente — sincroniza documentos aprovados do Notion
        ...
```

Registro em `src/app/console/schedule.py`:
```python
schedule.call(SyncKnowledgeBaseJob).hourly()
```

### Commands

```python
# src/app/console/commands/documents_ingest_command.py
from src.support.core.console.command import Command


class DocumentsIngestCommand(Command):
    signature = "documents:ingest {page_id:str} {--force:bool}"
    description = "Ingere um documento aprovado do Notion na base de conhecimento."

    async def handle(self):
        # self.input == {"page_id": ..., "force": bool}
        ...
```

Registro: **automático**. Basta o arquivo existir em `src/app/console/commands/` que o `cli.py` (via `load_commands`) descobre e expõe `python cli.py documents:ingest ...`.

DSL da `signature` (resumo):

- `{name:type}` — argumento posicional obrigatório (`type` ∈ str/int/float/bool, default `str`).
- `{--flag:bool}` — flag booleana (`--flag/--no-flag`, default `False`).
- `{--option:type=}` — opção com valor (`--option VALUE`, default `None`).

`handle()` pode ser sync ou `async def` — o loader detecta e roda `asyncio.run()` quando necessário.

### Scaffolding (`make:*` commands)

Para criar artefatos novos (Entity, Model, Action, Controller, subdomínio inteiro, etc.), prefira `python cli.py make:*` em vez de criar arquivo manualmente — geram código no padrão do projeto e fazem auto-wiring de `__init__.py` e `database/env.py`. Tabela completa em **`docs/scaffolding-guide.md`**.

- Subdomínio novo do zero: `make:domain {nome}` (esqueleto + CRUD pronto).
- Extensões pontuais: `make:action {ctx} {VerboSubstantivo}`, `make:controller`, `make:request`, `make:response`, `make:job`, etc.

Comandos falham cedo se o arquivo já existe; use `--force` apenas com confirmação do usuário.

## Fluxos comuns

### Criar um novo subdomínio

Ver guia completo em **`docs/adding-new-domain.md`**. Resumo:

1. Crie `src/domain/{contexto}/` com `entities/`, `models/`, `actions/`, `repositories/`, `mappers/`, `dtos/`, `enums/` (se aplicável).
2. Defina Entity (dataclass) + Model (SQLAlchemy).
3. Implemente Mapper (`src/domain/{ctx}/mappers/`) e Repository que delega a ele para conversão Entity ↔ Model.
4. Crie Actions para cada caso de uso.
5. Crie Controller em `src/app/api/controllers/`.
6. Crie Request/Response schemas em `src/app/api/requests/` e `responses/`.
7. Crie rota em `src/app/api/routes/{contexto}.py` (autodiscovery).
8. Migration via Alembic.
9. Seed se houver dados base.
10. Testes.

### Criar uma nova Action

1. Arquivo em `src/domain/{contexto}/actions/{verbo}_{substantivo}_action.py`.
2. Classe `{Verbo}{Substantivo}Action` com `__init__` (dependências) e `execute()` (lógica).
3. Trabalha com Entities, não Models.
4. Lança exceções de domínio (`src/support/core/exceptions.py`) — controllers traduzem para HTTPException.

### Criar um Job agendado

Ver o resumo em `docs/architecture.md` → seção "Console e jobs". Resumo:

1. Classe em `src/app/console/jobs/{nome}_job.py` herdando `Job`, implementando `async def action()`.
2. Registrar cadência em `src/app/console/schedule.py` via DSL (`.daily`, `.hourly`, `.cron`, ...).
3. Scheduler detecta automaticamente no boot se `ENABLE_SCHEDULER=true`.

### Criar um Seed

1. Classe em `database/seeds/{nome}_seed.py` com `@staticmethod async def seed()`.
2. Adicionar à lista em `database/seeds/__init__.py`.
3. `python -m database.seeds` — roda apenas seeds ainda não executadas.

## Comandos úteis

```bash
# Subir aplicação em dev
uvicorn main:app --reload

# Migrations
alembic revision --autogenerate -m "descrição"
alembic upgrade head
alembic downgrade -1

# Seeds
python -m database.seeds

# Testes
pytest
pytest tests/unit
pytest -k "document"

# Lint
prospector

# Validação rápida
python -c "from main import app; print('OK')"
alembic check
```

## Antes de fazer mudanças estruturais

Se a tarefa envolve **criar pastas novas, mover arquivos entre camadas, ou mudar wiring de dependências**, pare e confirme antes de executar. A estrutura é deliberada — mudanças ad-hoc erodem a arquitetura.

Se a mudança altera o **pipeline do turno ou da ingestão** (etapa nova, etapa
removida, arquivo renomeado), atualize `frontend/src/features/ops/architectureMap.ts`
**no mesmo commit**. O teste `architectureMap.test.ts` falha se um arquivo
declarado no mapa deixar de existir — é o que impede a página de ops de mentir
sobre a arquitetura.

## Onde encontrar mais

### Documentação operacional (leia quando precisar fazer algo)

- **`docs/architecture.md`** — visão completa: camadas, fluxos, context vars, scheduler, integração Notion/MCP.
- **`docs/actions-vs-services.md`** — quando criar Action, quando criar Domain Service, quando nada disso.
- **`docs/conventions.md`** — naming, estilo, mixins, padrões de código detalhados.
- **`docs/adding-new-domain.md`** — guia passo a passo para novo subdomínio.
- **`docs/database-guide.md`** — migrations, seeds, factories, dual engine.
- **`docs/testing-guide.md`** — testes em projeto com context vars.
- **`docs/scaffolding-guide.md`** — comandos `make:*`.
- **`src/support/core/scheduling/README.md`** — referência operacional do scheduler (deployment, jobstore).

### Decisões arquiteturais (ADRs — leia quando precisar entender o *porquê*)

ADRs registram **o raciocínio por trás** de decisões importantes. Consulte quando:

- Uma regra acima parecer estranha e você quiser entender a motivação.
- Estiver considerando uma mudança que contraria uma regra existente.
- Precisar tomar decisão derivada e quiser alinhamento com princípios já estabelecidos.

**Padrão de leitura progressiva — importante para economizar contexto:**

Cada ADR tem `## Resumo` logo após o Status, separada do corpo completo por `---`. O Resumo contém três blocos: **Decisão**, **Aplica-se quando**, **Regra prática**. Fluxo recomendado:

1. **Comece por `docs/adr/README.md` (seção "Índice de ADRs")** — tabela com todos os ADRs em uma linha cada.
2. **Leia apenas a seção `## Resumo`** do ADR candidato — se bastar ou não se aplicar, pare aqui.
3. **Leia o corpo completo (abaixo do `---`)** apenas se precisar do racional detalhado.

**Regras de uso:**

- ADRs são **imutáveis**. Para mudar uma decisão, crie um ADR novo que substitua o anterior.
- **Antes de criar um ADR novo, leia `docs/adr/README.md`.**
- **Todo ADR novo deve ter `## Resumo` no topo**, seguindo o template do guia.

ADRs atuais (em `docs/adr/`):

- **ADR-0001** — Adotar estrutura Spatie-like (`src/{app, domain, support}`)
- **ADR-0002** — Organizar `domain/` por bounded context (subdomínio)
- **ADR-0003** — Separar Entities (dataclass) de Models (SQLAlchemy)
- **ADR-0004** — Actions com sufixo `Action` e `execute()`, sem Service facade
- **ADR-0005** — Usar SQLAlchemy 2.0 em vez de SQLModel
- **ADR-0006** — Sessão DB via ContextVar + middleware
- **ADR-0016** — Framework do agente = LangGraph, observabilidade fina no LangSmith (substitui o ADR-0007)
- **ADR-0017** — Plataforma Borderless como IdP; sem Supabase (validação/sessão substituídas pelo 0018)
- **ADR-0018** — Auth vira BFF: token opaco da plataforma vive só no servidor; cookie httpOnly; `pyjwt` removido
- **ADR-0019** — O turno do oráculo é entregue como eventos AG-UI (contrato substituído pelo 0021; SSE mantido)
- **ADR-0020** — A fase 1 do turno roda no corpo SSE, em escopo de sessão próprio (revisa o consumo em duas fases do 0016)
- **ADR-0021** — O turno é entregue como `StreamEvent` do `astream_events`, redigido no runner (substitui o contrato do 0019)
- **ADR-0022** — Tool de navegação: nó `navigate` dedicado (não `ToolNode`), sessões por bearer da Platform e catálogo de destinos buscado por turno

Índice completo em `docs/adr/README.md`.

## Em caso de dúvida

Se a situação não estiver coberta nestes documentos, **pergunte antes de adivinhar**. Decisões novas com impacto arquitetural exigem ADR antes da implementação — ver `docs/adr/README.md`.
