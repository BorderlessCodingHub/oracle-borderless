# Actions vs Services

Este documento explica como decidir, na arquitetura-alvo, se um pedaço de lógica vira **Action** ou **Domain Service** — e por que **não existe Service facade** neste projeto.

Para arquitetura geral, ver `docs/architecture.md`. Para naming e estilo, ver `docs/conventions.md`.

## A regra principal

Quase tudo que parece "Service" no Laravel/FastAPI tradicional vira **Action** aqui. Domain Services são raros e existem só para lógica que genuinamente não cabe em uma única Action nem em uma Entity.

| Tipo | Pasta | Quando usar |
|---|---|---|
| **Action** | `src/domain/{ctx}/actions/` | Caso de uso (ingerir documento, responder pergunta, listar) |
| **Domain Service** | `src/domain/{ctx}/services/` | Lógica de domínio sem dono natural (cálculo, validador complexo, regra ampla) |
| **Method em Entity** | `src/domain/{ctx}/entities/{nome}.py` | Comportamento que pertence à entidade (`document.is_approved()`) |
| **Mapper** | `src/domain/{ctx}/mappers/` | Conversão Entity ↔ Model (`DocumentMapper.to_entity(model)`, `to_model_attrs(entity)`) |
| **Client** | `src/support/clients/` | Integração externa (HTTP, MCP/Notion, LLM, fila) |

## Actions

### Características

- **Uma classe, um método público (`execute()`)**, um caso de uso.
- Sufixo **`Action`** no nome: `IngestDocumentAction`, `UpdateDocumentAction`, `OpenTurnAction`.
- Recebe **DTOs** ou primitivos em `execute()`. Retorna **Entity** ou tipos primitivos.
- Recebe dependências externas (clients, outros services) no `__init__`. Repository é instanciado direto (pega session do contexto).
- Lança **exceções de domínio** (`DomainError` e subclasses), nunca `HTTPException`.
- Pode chamar **outras Actions** quando precisa compor.

### Exemplo

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
            uuid=None,
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

### Composição: Actions chamam Actions

Não há Service facade. Quando uma operação coordena múltiplas Actions, **uma Action chama outras**:

```python
# src/domain/documents/actions/sync_from_notion_action.py
class SyncFromNotionAction:
    """Orquestra: lista páginas aprovadas + ingere cada nova + reindexa a base."""

    def __init__(self, notion_client: NotionClient):
        self.notion = notion_client
        self.ingest_document_action = IngestDocumentAction(notion_client)
        self.reindex_action = ReindexKnowledgeBaseAction()

    async def execute(self) -> list[Document]:
        pages = await self.notion.list_approved_pages()
        ingested = []
        for page in pages:
            document = await self.ingest_document_action.execute(
                DocumentIngestData(notion_page_id=page.id)
            )
            ingested.append(document)
        await self.reindex_action.execute()
        return ingested
```

**Vantagens vs Service facade:**
- Cada Action permanece testável independentemente.
- A coordenação é explícita, não escondida atrás de método estático.
- Pode reusar as Actions individuais em outros contextos (CLI, jobs).

### Quando criar uma Action

Responda sim a todas:

1. A operação pode ser descrita como **verbo no imperativo**? ("Ingerir documento", "Listar documentos", "Responder pergunta")
2. Tem **entrada e saída bem definidas**?
3. É **invocável de múltiplos lugares** (HTTP, CLI, job)?
4. Tem **regra de negócio real**, não é só CRUD direto?

Se sim → Action.

### Exemplos no projeto

```
src/domain/documents/actions/
├── ingest_document_action.py
├── update_document_action.py
├── archive_document_action.py
├── get_document_action.py
├── list_documents_action.py
└── sync_from_notion_action.py

src/domain/conversations/actions/
├── start_conversation_action.py
├── answer_question_action.py
└── list_conversations_action.py
```

## Domain Services

### Características

- **Lógica de domínio que não tem dono natural** entre as Entities.
- Tipicamente envolve múltiplas Entities ou regras complexas isoladas.
- Sufixo **`Service`** no nome: `ContentSanitizerService`, `RelevanceScorerService`.
- Pode ser função pura (sem estado) ou classe com estado mínimo.
- Usado **por Actions**, não diretamente por controllers.

### Exemplo

```python
# src/domain/documents/services/content_sanitizer_service.py
from dataclasses import dataclass


@dataclass
class SanitizationResult:
    is_safe: bool
    flagged_terms: list[str]


class ContentSanitizerService:
    """Verifica se um documento contém marcadores de conteúdo confidencial
    antes de entrar na base consultável pelo oráculo."""

    CONFIDENTIAL_MARKERS = ("confidencial", "restrito", "não divulgar")

    def check(self, content: str) -> SanitizationResult:
        lowered = content.lower()
        flagged = [m for m in self.CONFIDENTIAL_MARKERS if m in lowered]
        return SanitizationResult(is_safe=len(flagged) == 0, flagged_terms=flagged)
```

Usado por Action:

```python
class IngestDocumentAction:
    def __init__(self, notion_client: NotionClient):
        self.sanitizer = ContentSanitizerService()
        ...

    async def execute(self, data: DocumentIngestData) -> Document:
        page = await self.notion.get_page(data.notion_page_id)
        result = self.sanitizer.check(page.content)
        if not result.is_safe:
            raise ValidationError("Conteúdo confidencial detectado", details=result.flagged_terms)
        ...
```

### Quando criar Domain Service

- A lógica é **pura** (não tem efeitos colaterais como I/O).
- Não pertence claramente a uma única Entity.
- Reutilizada em **múltiplas Actions**.
- Tem **identidade conceitual** no domínio (existe um nome no negócio: "Sanitizador de conteúdo", "Pontuador de relevância").

### Exemplos válidos

- `ContentSanitizerService` — detecta marcadores de conteúdo confidencial.
- `RelevanceScorerService` — pontua relevância de trechos para uma pergunta.
- `CitationBuilderService` — monta citações de fonte a partir de documentos.

### Exemplos NÃO válidos (e o que fazer em vez)

- ❌ `DocumentService` com 20 métodos de CRUD → quebrar em Actions individuais.
- ❌ `HttpFetcher` (faz HTTP) → vai em `src/support/clients/`.
- ❌ `SlugGenerator` genérico → vai em `src/support/utils/`.
- ❌ `DocumentApprovalChecker` que só lê `document.status` → vira método em `Document` Entity.

## Methods em Entities

Comportamento que pertence à entidade vai como método na própria Entity:

```python
@dataclass
class Document:
    uuid: UUID
    status: str
    deleted_at: datetime | None

    def is_approved(self) -> bool:
        return self.status == "approved" and self.deleted_at is None

    def is_indexable(self) -> bool:
        return self.is_approved()

    def is_archived(self) -> bool:
        return self.status == "archived"
```

**Sinal claro:** se você está criando um Service que recebe a entidade como primeiro parâmetro e mexe nela, provavelmente é método da entidade.

```python
# ❌ Modelo anêmico
class DocumentService:
    @staticmethod
    def is_approved(document: Document) -> bool:
        return document.status == "approved"

# ✓ Comportamento na entidade
@dataclass
class Document:
    def is_approved(self) -> bool:
        return self.status == "approved" and self.deleted_at is None
```

## Clients (integrações externas)

Tudo que sai do processo (HTTP, MCP/Notion, LLM, fila) é **Client** em `src/support/clients/`. Actions injetam Clients no `__init__`.

```python
# src/support/clients/notion/notion_client.py
class NotionClient:
    async def get_page(self, page_id: str) -> NotionPage: ...
    async def list_approved_pages(self) -> list[NotionPage]: ...

# Action recebe via __init__
class IngestDocumentAction:
    def __init__(self, notion_client: NotionClient):
        self.notion = notion_client
```

**Por que Clients ficam em `support/`:** são infraestrutura técnica reutilizada por múltiplos subdomínios. Não pertencem a um domínio específico.

**Exceção:** se um Client é radicalmente específico de um único subdomínio e nunca será reusado, pode ficar em `src/domain/{ctx}/clients/` — mas isso é raro.

## Árvore de decisão

```
Vou criar lógica nova. O que é?
│
├─ Caso de uso completo (verbo + substantivo)?
│  → ✅ Action em src/domain/{ctx}/actions/
│
├─ Comportamento que pertence a uma única entity?
│  → ✅ Método na Entity em src/domain/{ctx}/entities/
│
├─ Cálculo/validação/regra que envolve múltiplas entities ou
│  é pura mas reusada em várias Actions?
│  → ✅ Domain Service em src/domain/{ctx}/services/
│
├─ Integração externa (HTTP, MCP/Notion, LLM, fila)?
│  → ✅ Client em src/support/clients/
│
├─ Helper genérico técnico (formatador, parser, gerador de slug)?
│  → ✅ Util em src/support/utils/
│
└─ Múltiplas Actions precisam ser orquestradas?
   → ✅ Outra Action que chama as Actions menores
      (NÃO crie Service facade)
```

## Anti-padrões

### ❌ Service facade agregador

```python
# src/domain/documents/services/document_service.py
class DocumentService:
    @staticmethod
    async def ingest_document(data): ...
    @staticmethod
    async def update_document(id, data): ...
    @staticmethod
    async def archive_document(id): ...
    @staticmethod
    async def list_documents(): ...
```

**Problema:** vira lixeira. Cada método é uma Action disfarçada. Atrapalha teste, atrapalha leitura, atrapalha reuso.

**Alternativa:** uma Action por arquivo, em `src/domain/documents/actions/`.

### ❌ Action anêmica

```python
class ListDocumentsAction:
    def __init__(self):
        self.repository = DocumentRepository()

    async def execute(self):
        return await self.repository.list_documents()
```

**Problema:** wrapper sem valor. Repete o repositório.

**Alternativa:** se o caso de uso é só "listar com regra X", e a regra está toda no repositório, **chame o repositório direto do controller**:

```python
class DocumentController:
    @staticmethod
    async def list_documents():
        repository = DocumentRepository()
        documents = await repository.list_documents()
        return [DocumentResponse.from_entity(d) for d in documents]
```

Mas atenção: muitas vezes a Action é justificada porque vai crescer (adicionar filtros, paginação inteligente, autorização). Não evite Action por preguiça — evite por falta genuína de regra.

### ❌ Action inchada

```python
class IngestDocumentAction:
    async def execute(self, data):
        page = await self._fetch_from_notion(data)
        await self._sanitize(page)
        await self._persist(page)
        await self._generate_embeddings(page)
        await self._reindex_everything()
        await self._notify_admins(page)
        return page
```

**Problema:** "ingerir documento" virou o pipeline inteiro de sincronização.

**Alternativa:** Action `IngestDocumentAction` enxuta + Action `SyncFromNotionAction` que compõe:

```python
class SyncFromNotionAction:
    async def execute(self):
        for page in await self.notion.list_approved_pages():
            await self.ingest_document_action.execute(DocumentIngestData(notion_page_id=page.id))
        await self.reindex_action.execute()
```

### ❌ Domain Service que deveria ser método em Entity

```python
class DocumentService:
    @staticmethod
    def is_approved(document: Document) -> bool: ...

    @staticmethod
    def is_indexable(document: Document) -> bool: ...
```

**Problema:** lógica que pertence ao `Document` está fora dele. Modelo anêmico.

**Alternativa:**

```python
@dataclass
class Document:
    status: str
    deleted_at: datetime | None

    def is_approved(self) -> bool:
        return self.status == "approved" and self.deleted_at is None

    def is_indexable(self) -> bool:
        return self.is_approved()
```

### ❌ Action que importa FastAPI ou Pydantic

```python
class IngestDocumentAction:
    async def execute(self, data):
        ...
        raise HTTPException(status_code=409, detail="...")  # ❌
```

**Problema:** Action virou dependente de framework HTTP. Não roda em job ou CLI.

**Alternativa:** lança exceção de domínio; controller traduz.

```python
# src/support/core/exceptions.py
class DomainConflictError(DomainError): pass

# src/domain/documents/actions/ingest_document_action.py
raise DomainConflictError(f"Documento {data.notion_page_id} já foi ingerido")

# src/app/api/exception_handlers.py
@app.exception_handler(DomainConflictError)
async def handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
```

## Em caso de dúvida

Três perguntas úteis:

1. **Esta lógica precisa rodar em job ou CLI também?** Sim → Action; ela não pode acoplar a HTTP.
2. **Se eu fosse nomear no imperativo, faria sentido?** Sim → Action. Não → Service ou método em entidade.
3. **A lógica tem dono natural entre as entidades?** Sim → vai na entidade. Não → Service (se coeso) ou Action (se tarefa única).

Casos genuinamente difíceis: **registre a decisão no PR** ou abra um ADR se for padrão recorrente.
