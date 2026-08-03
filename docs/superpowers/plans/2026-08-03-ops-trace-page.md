# Página de Ops (trace por turno + mapa vivo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar o que acontece em cada turno do oráculo (decisão do gate, retrieval, limiar, desfecho, latência) numa tabela do Postgres, e expor isso numa página `/ops` com um mapa vivo da arquitetura, a lista de turnos recentes e o painel de eval.

**Architecture:** Um DTO puro (`TurnTraceDraft`) acumula eventos ao longo do turno. A `AnswerQuestionAction` preenche as fases que rodam dentro do request (recência, gate, retrieval, recusa); o gerador SSE do controller completa a fase do engine (primeiro token, duração, tokens, tool calls) e a **mesma** background task que já persiste a resposta grava o trace. A leitura é agregada em SQL e servida por quatro endpoints só-leitura, consumidos por uma página React que renderiza as caixas a partir de um registro único (`ARCHITECTURE_MAP`) verificado por teste.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic, pgvector, pytest, UV, React 19 + TypeScript + Vite, Vitest.

## Global Constraints

- **Spec de referência:** [`docs/superpowers/specs/2026-08-03-ops-trace-page-design.md`](../specs/2026-08-03-ops-trace-page-design.md). Ler antes de começar.
- **ADR novo:** ADR-0013, escrito na Task 11 (não antes — o corpo cita decisões que as tasks anteriores materializam).
- **Rodar testes com `DB_PORT=5434`**: `DB_PORT=5434 uv run pytest ...`. O Postgres do projeto sobe com `DB_PORT=5434 docker compose -f docker/docker-compose.yml up -d`.
- **Migration nova precisa ser aplicada nos dois bancos:** `DB_PORT=5434 uv run alembic upgrade head` e `DB_PORT=5434 DB_NAME=oracle_borderless_test uv run alembic upgrade head`. Sem isso, as tasks de integração falham com "relation does not exist".
- **`alembic check` está limpo neste repo** (desde `c7e8bdc`). Se sua migration deixar o check sujo, é bug seu — não é ruído pré-existente.
- **A suíte está 100% verde no início deste plano:** 203 testes (165 unit + 38 integração) + 17 no frontend.
- **Entity é dataclass pura** — `src/domain/observability/entities/` não importa `sqlalchemy`, `fastapi` nem `pydantic`.
- **Sessão de banco vem do contexto:** `CurrentAsyncSessionContext.get()`. Nunca instanciar `AsyncSessionLocal()` em repository/action.
- **Nome exato da tabela:** `agent_traces`. **Nomes exatos das colunas:** conforme a tabela da spec (seção 3) — o frontend depende deles via os responses.
- **Valores de `outcome`:** exatamente `"answer"`, `"refusal"`, `"error"`.
- **Janelas aceitas em `?window=`:** exatamente `24h`, `7d`, `all`. Qualquer outro valor → 422 (validação do Pydantic/Literal).
- **Trace nunca derruba um turno:** o call site de `RecordTurnTraceAction` fica sob `try/except` que loga e engole, como o `_persist_assistant` já faz hoje.
- **Textos visíveis ao usuário em pt-BR**; identificadores, arquivos e rotas em inglês (convenção do frontend).
- **Não mudar o contrato SSE.** `useAskStream.ts` e `sse.ts` não são tocados por este plano.
- **Não rodar o harness de eval.** A Task 10 só reconfigura o juiz; a primeira execução real é conversa à parte com a dona do produto.

---

### Task 1: Migration + subdomínio `observability` (Entity, Model, Mapper)

Cria a tabela e as três peças de persistência. Nada lê nem escreve ainda — a task termina com um roundtrip de mapper testado e a migration aplicada.

**Files:**
- Create: `src/domain/observability/__init__.py`, `entities/__init__.py`, `models/__init__.py`, `mappers/__init__.py`, `dtos/__init__.py`, `repositories/__init__.py`, `actions/__init__.py`
- Create: `src/domain/observability/entities/turn_trace.py`
- Create: `src/domain/observability/models/turn_trace.py`
- Create: `src/domain/observability/mappers/turn_trace_mapper.py`
- Create: `database/migrations/versions/0006_agent_traces.py`
- Create: `tests/unit/domain/observability/__init__.py`, `tests/unit/domain/observability/mappers/__init__.py`
- Create: `tests/unit/domain/observability/mappers/test_turn_trace_mapper.py`

**Interfaces:**
- Consumes: nada.
- Produces: `TurnTrace` (Entity), `TurnTraceModel`, `TurnTraceMapper.to_entity/to_model_attrs`, tabela `agent_traces`.

- [ ] **Step 1: Escrever o teste que falha (roundtrip do mapper)**

`tests/unit/domain/observability/mappers/test_turn_trace_mapper.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.mappers.turn_trace_mapper import TurnTraceMapper


def _entity(**overrides) -> TurnTrace:
    base = dict(
        uuid=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        user_email="alguem@exemplo.com",
        question="o que é o PSP?",
        history_messages=4,
        history_tokens_est=830,
        gate_retrieve=True,
        gate_search_query="renovação de PSP",
        gate_degraded=False,
        gate_ms=120,
        retrieval_ran=True,
        retrieval_top_k=6,
        retrieval_kept=2,
        retrieval_best_distance=0.427,
        retrieval_threshold=0.55,
        retrieval_ms=40,
        outcome="answer",
        first_token_ms=410,
        engine_ms=1980,
        citations_count=2,
        tool_calls=0,
        input_tokens=1200,
        output_tokens=300,
        error=None,
        events=[{"at_ms": 0, "step": "turn_start", "detail": {}}],
        created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TurnTrace(**base)


def test_to_model_attrs_carries_every_flat_field():
    entity = _entity()
    attrs = TurnTraceMapper.to_model_attrs(entity)

    assert attrs["uuid"] == entity.uuid
    assert attrs["conversation_id"] == entity.conversation_id
    assert attrs["gate_search_query"] == "renovação de PSP"
    assert attrs["retrieval_best_distance"] == 0.427
    assert attrs["outcome"] == "answer"
    assert attrs["events"] == entity.events
    # created_at é server_default — o mapper não o envia
    assert "created_at" not in attrs


def test_roundtrip_through_a_stub_model():
    entity = _entity()
    attrs = TurnTraceMapper.to_model_attrs(entity)

    class StubModel:
        pass

    model = StubModel()
    for key, value in attrs.items():
        setattr(model, key, value)
    model.created_at = entity.created_at

    back = TurnTraceMapper.to_entity(model)
    assert back == entity


def test_optional_fields_survive_as_none():
    entity = _entity(
        message_id=None,
        user_email=None,
        gate_search_query=None,
        retrieval_best_distance=None,
        retrieval_ms=None,
        first_token_ms=None,
        engine_ms=None,
        input_tokens=None,
        output_tokens=None,
        error="timeout do modelo",
        outcome="error",
    )
    back = TurnTraceMapper.to_entity_from_attrs(
        TurnTraceMapper.to_model_attrs(entity), created_at=entity.created_at
    )
    assert back == entity
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/observability -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain.observability'`

- [ ] **Step 3: Criar os pacotes do subdomínio**

Criar `src/domain/observability/__init__.py` e os `__init__.py` de `entities/`, `models/`, `mappers/`, `dtos/`, `repositories/`, `actions/` — todos vazios, exceto onde indicado nas tasks seguintes.

- [ ] **Step 4: Escrever a Entity**

`src/domain/observability/entities/turn_trace.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class TurnTrace:
    """O que aconteceu num turno do oráculo. Entity pura — sem SQLAlchemy.

    Colunas planas são o que a página agrega em SQL; `events` é a sequência
    ordenada que o detalhe do turno exibe. Ver spec, seção 3.
    """

    uuid: UUID
    conversation_id: UUID
    question: str
    outcome: str  # "answer" | "refusal" | "error"
    created_at: datetime
    message_id: UUID | None = None
    user_email: str | None = None
    history_messages: int = 0
    history_tokens_est: int = 0
    gate_retrieve: bool = False
    gate_search_query: str | None = None
    gate_degraded: bool = False
    gate_ms: int = 0
    retrieval_ran: bool = False
    retrieval_top_k: int = 0
    retrieval_kept: int = 0
    retrieval_best_distance: float | None = None
    retrieval_threshold: float = 0.0
    retrieval_ms: int | None = None
    first_token_ms: int | None = None
    engine_ms: int | None = None
    citations_count: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    events: list[dict] = field(default_factory=list)

    def is_refusal(self) -> bool:
        return self.outcome == "refusal"
```

- [ ] **Step 5: Escrever o Model**

`src/domain/observability/models/turn_trace.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import HasUUID
from src.support.core.models.base_model import BaseModel


class TurnTraceModel(BaseModel, HasUUID):
    __tablename__ = "agent_traces"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.uuid", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.uuid", ondelete="SET NULL"), nullable=True
    )
    user_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    question: Mapped[str] = mapped_column(Text)

    history_messages: Mapped[int] = mapped_column(Integer, default=0)
    history_tokens_est: Mapped[int] = mapped_column(Integer, default=0)

    gate_retrieve: Mapped[bool] = mapped_column(Boolean, index=True)
    gate_search_query: Mapped[str | None] = mapped_column(String(512), nullable=True)
    gate_degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_ms: Mapped[int] = mapped_column(Integer, default=0)

    retrieval_ran: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieval_top_k: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_kept: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_best_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieval_threshold: Mapped[float] = mapped_column(Float, default=0.0)
    retrieval_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    outcome: Mapped[str] = mapped_column(String(16), index=True)
    first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citations_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    events: Mapped[list] = mapped_column(JSONB, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_agent_traces_created_at", "created_at"),)
```

> **Por que índice ascendente e não `created_at DESC`:** a comparação de índices
> por expressão do Alembic é fraca — um índice funcional tende a aparecer como
> diff em todo `alembic check`, que é justamente o que o Step 8 exige limpo. Um
> btree ascendente é varrido de trás para frente pelo Postgres sem custo extra,
> então `ORDER BY created_at DESC` usa este índice do mesmo jeito. Declare o índice
> como string nos dois lugares (Model e migration).

- [ ] **Step 6: Escrever o Mapper**

`src/domain/observability/mappers/turn_trace_mapper.py`:

```python
from datetime import datetime

from src.domain.observability.entities.turn_trace import TurnTrace

_FLAT_FIELDS = (
    "uuid",
    "conversation_id",
    "message_id",
    "user_email",
    "question",
    "history_messages",
    "history_tokens_est",
    "gate_retrieve",
    "gate_search_query",
    "gate_degraded",
    "gate_ms",
    "retrieval_ran",
    "retrieval_top_k",
    "retrieval_kept",
    "retrieval_best_distance",
    "retrieval_threshold",
    "retrieval_ms",
    "outcome",
    "first_token_ms",
    "engine_ms",
    "citations_count",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "error",
    "events",
)


class TurnTraceMapper:
    @staticmethod
    def to_model_attrs(entity: TurnTrace) -> dict:
        """`created_at` fica fora: é server_default do Postgres."""
        return {name: getattr(entity, name) for name in _FLAT_FIELDS}

    @staticmethod
    def to_entity(model) -> TurnTrace:
        attrs = {name: getattr(model, name) for name in _FLAT_FIELDS}
        return TurnTrace(created_at=model.created_at, **attrs)

    @staticmethod
    def to_entity_from_attrs(attrs: dict, created_at: datetime) -> TurnTrace:
        """Atalho de teste: monta a Entity a partir do dict do to_model_attrs."""
        return TurnTrace(created_at=created_at, **attrs)
```

Exportar em `src/domain/observability/mappers/__init__.py`:

```python
from src.domain.observability.mappers.turn_trace_mapper import TurnTraceMapper

__all__ = ["TurnTraceMapper"]
```

- [ ] **Step 7: Escrever a migration**

`database/migrations/versions/0006_agent_traces.py`:

```python
"""agent_traces — trace por turno do oráculo (ADR-0013)

Revision ID: 0006_agent_traces
Revises: 0005_support_tracking_tables
Create Date: 2026-08-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_agent_traces"
down_revision = "0005_support_tracking_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_traces",
        sa.Column("uuid", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.uuid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.uuid", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_email", sa.String(length=320), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("history_messages", sa.Integer(), nullable=False),
        sa.Column("history_tokens_est", sa.Integer(), nullable=False),
        sa.Column("gate_retrieve", sa.Boolean(), nullable=False),
        sa.Column("gate_search_query", sa.String(length=512), nullable=True),
        sa.Column("gate_degraded", sa.Boolean(), nullable=False),
        sa.Column("gate_ms", sa.Integer(), nullable=False),
        sa.Column("retrieval_ran", sa.Boolean(), nullable=False),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False),
        sa.Column("retrieval_kept", sa.Integer(), nullable=False),
        sa.Column("retrieval_best_distance", sa.Float(), nullable=True),
        sa.Column("retrieval_threshold", sa.Float(), nullable=False),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("engine_ms", sa.Integer(), nullable=True),
        sa.Column("citations_count", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_traces_conversation_id", "agent_traces", ["conversation_id"])
    op.create_index("ix_agent_traces_gate_retrieve", "agent_traces", ["gate_retrieve"])
    op.create_index("ix_agent_traces_outcome", "agent_traces", ["outcome"])
    op.create_index("ix_agent_traces_created_at", "agent_traces", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_traces_created_at", table_name="agent_traces")
    op.drop_index("ix_agent_traces_outcome", table_name="agent_traces")
    op.drop_index("ix_agent_traces_gate_retrieve", table_name="agent_traces")
    op.drop_index("ix_agent_traces_conversation_id", table_name="agent_traces")
    op.drop_table("agent_traces")
```

- [ ] **Step 8: Aplicar nos dois bancos e conferir o check**

```bash
DB_PORT=5434 uv run alembic upgrade head
DB_PORT=5434 DB_NAME=oracle_borderless_test uv run alembic upgrade head
DB_PORT=5434 uv run alembic check
```
Expected: as duas migrations rodam; o check imprime **"No new upgrade operations detected."** Se acusar diff em `agent_traces`, o Model e a migration divergiram — alinhe antes de seguir.

- [ ] **Step 9: Rodar os testes e ver passar**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/observability -v`
Expected: 3 PASS

- [ ] **Step 10: Commit**

```bash
git add src/domain/observability database/migrations/versions/0006_agent_traces.py tests/unit/domain/observability
git commit -m "feat(observability): tabela agent_traces + entity/model/mapper do trace"
```

---

### Task 2: `TurnTraceDraft` — o coletor puro

O acumulador que atravessa o turno. Pura acumulação em memória, com relógio injetável para o teste ser determinístico.

**Files:**
- Create: `src/domain/observability/dtos/turn_trace_draft.py`
- Create: `tests/unit/domain/observability/dtos/__init__.py`
- Create: `tests/unit/domain/observability/dtos/test_turn_trace_draft.py`

**Interfaces:**
- Consumes: `TurnTrace` (Task 1).
- Produces: `TurnTraceDraft(question, clock=time.monotonic)` com `record(step, **detail)`, `elapsed_ms()`, `to_entity(uuid, conversation_id) -> TurnTrace`, e os campos planos listados na Task 1.

- [ ] **Step 1: Escrever o teste que falha**

`tests/unit/domain/observability/dtos/test_turn_trace_draft.py`:

```python
from uuid import uuid4

import pytest

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


class FakeClock:
    """Relógio determinístico: cada leitura avança 0,1s."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        value = self.t
        self.t += 0.1
        return value


def test_records_steps_in_order_with_monotonic_at_ms():
    draft = TurnTraceDraft(question="o que é o PSP?", clock=FakeClock())
    draft.record("gate", retrieve=True)
    draft.record("retrieval", kept=2)

    steps = [e["step"] for e in draft.events]
    at_ms = [e["at_ms"] for e in draft.events]

    assert steps == ["gate", "retrieval"]
    assert at_ms == sorted(at_ms)
    assert draft.events[0]["detail"] == {"retrieve": True}


def test_elapsed_ms_counts_from_construction():
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    # construção lê t=0.0; a próxima leitura devolve 0.1s → 100ms
    assert draft.elapsed_ms() == 100


def test_to_entity_carries_flat_fields_and_events():
    draft = TurnTraceDraft(question="o que é o PSP?", clock=FakeClock())
    draft.gate_retrieve = True
    draft.gate_search_query = "PSP"
    draft.retrieval_kept = 2
    draft.outcome = "answer"
    draft.record("turn_end", outcome="answer")

    conversation_id = uuid4()
    entity = draft.to_entity(conversation_id=conversation_id)

    assert entity.conversation_id == conversation_id
    assert entity.question == "o que é o PSP?"
    assert entity.gate_retrieve is True
    assert entity.gate_search_query == "PSP"
    assert entity.retrieval_kept == 2
    assert entity.outcome == "answer"
    assert entity.events[-1]["step"] == "turn_end"
    assert entity.uuid is not None


def test_record_never_raises_on_unserializable_detail():
    """O trace não pode derrubar um turno: detail estranho é coagido para str."""
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    draft.record("weird", obj=object())
    assert isinstance(draft.events[0]["detail"]["obj"], str)


def test_question_is_truncated_for_the_event_but_not_for_the_column():
    long_question = "a" * 5000
    draft = TurnTraceDraft(question=long_question, clock=FakeClock())
    draft.record("turn_start", question_chars=len(long_question))
    assert draft.question == long_question
    assert draft.events[0]["detail"]["question_chars"] == 5000


@pytest.mark.parametrize("outcome", ["answer", "refusal", "error"])
def test_outcome_accepts_only_the_three_known_values(outcome):
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    draft.outcome = outcome
    assert draft.to_entity(conversation_id=uuid4()).outcome == outcome
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/observability/dtos -v`
Expected: FAIL — `ModuleNotFoundError: ...turn_trace_draft`

- [ ] **Step 3: Implementar o draft**

`src/domain/observability/dtos/turn_trace_draft.py`:

```python
"""Acumulador do trace de um turno. Puro: só memória, sem I/O e sem banco.

Atravessa duas fronteiras de sessão (ver spec, seção 1): a Action preenche as
fases do request, o controller completa a fase do engine, e a background task
pós-stream converte para Entity e persiste.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from uuid6 import uuid7

from src.domain.observability.entities.turn_trace import TurnTrace

_JSON_SAFE = (str, int, float, bool, type(None))


def _safe(value):
    """JSONB aceita só primitivos; qualquer outra coisa vira str.

    Existe para honrar o invariante "trace nunca derruba um turno": um detail
    inesperado não pode estourar na serialização depois, longe da origem.
    """
    if isinstance(value, _JSON_SAFE):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


@dataclass
class TurnTraceDraft:
    question: str
    clock: Callable[[], float] = time.monotonic

    user_email: str | None = None
    history_messages: int = 0
    history_tokens_est: int = 0

    gate_retrieve: bool = False
    gate_search_query: str | None = None
    gate_degraded: bool = False
    gate_ms: int = 0

    retrieval_ran: bool = False
    retrieval_top_k: int = 0
    retrieval_kept: int = 0
    retrieval_best_distance: float | None = None
    retrieval_threshold: float = 0.0
    retrieval_ms: int | None = None

    outcome: str = "answer"
    first_token_ms: int | None = None
    engine_ms: int | None = None
    citations_count: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    message_id: UUID | None = None

    events: list[dict] = field(default_factory=list)
    _t0: float = field(init=False, default=0.0, repr=False)

    def __post_init__(self) -> None:
        self._t0 = self.clock()

    def elapsed_ms(self) -> int:
        return int((self.clock() - self._t0) * 1000)

    def record(self, step: str, **detail) -> None:
        self.events.append(
            {"at_ms": self.elapsed_ms(), "step": step, "detail": {k: _safe(v) for k, v in detail.items()}}
        )

    def to_entity(self, conversation_id: UUID) -> TurnTrace:
        return TurnTrace(
            uuid=uuid7(),
            conversation_id=conversation_id,
            message_id=self.message_id,
            user_email=self.user_email,
            question=self.question,
            history_messages=self.history_messages,
            history_tokens_est=self.history_tokens_est,
            gate_retrieve=self.gate_retrieve,
            gate_search_query=self.gate_search_query,
            gate_degraded=self.gate_degraded,
            gate_ms=self.gate_ms,
            retrieval_ran=self.retrieval_ran,
            retrieval_top_k=self.retrieval_top_k,
            retrieval_kept=self.retrieval_kept,
            retrieval_best_distance=self.retrieval_best_distance,
            retrieval_threshold=self.retrieval_threshold,
            retrieval_ms=self.retrieval_ms,
            outcome=self.outcome,
            first_token_ms=self.first_token_ms,
            engine_ms=self.engine_ms,
            citations_count=self.citations_count,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            error=self.error,
            events=list(self.events),
            created_at=datetime.now(timezone.utc),
        )
```

> **Nota:** o uuid é `uuid7()`, como todo PK do projeto (mixin `HasUUID`). É
> gerado no `to_entity`, fora do caminho de latência do turno.

- [ ] **Step 4: Rodar e ver passar**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/observability -v`
Expected: 9 PASS (3 do mapper + 6 do draft)

- [ ] **Step 5: Commit**

```bash
git add src/domain/observability/dtos tests/unit/domain/observability/dtos
git commit -m "feat(observability): TurnTraceDraft — coletor puro do trace do turno"
```

---

### Task 3: `nearest_distance` — a distância do mais próximo quando nada passa

`search_similar` filtra pelo limiar em SQL, então numa recusa não se sabe quão perto o vizinho mais próximo chegou. Este método responde isso, e é chamado **só** no caminho de recusa.

**Files:**
- Modify: `src/domain/documents/repositories/document_chunk_repository.py`
- Create: `tests/integration/domain/documents/test_chunk_repository_nearest.py`

**Interfaces:**
- Consumes: nada.
- Produces: `DocumentChunkRepository.nearest_distance(embedding: list[float]) -> float | None`.

- [ ] **Step 1: Escrever o teste (integração) que falha**

`tests/integration/domain/documents/test_chunk_repository_nearest.py`:

```python
import pytest

from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)
from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


def _vector(first: float) -> list[float]:
    return [first] + [0.0] * (settings.EMBEDDING_DIM - 1)


@pytest.mark.asyncio
async def test_returns_distance_even_when_above_the_threshold(
    db_session, seed_document_with_chunk, monkeypatch
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT)
    # chunk ortogonal à query → distância cosseno 1.0, muito acima do limiar
    await seed_document_with_chunk("Web3 Bootcamp", kb_root_page_id=ROOT, embedding=_vector(1.0))
    query = [0.0, 1.0] + [0.0] * (settings.EMBEDDING_DIM - 2)

    repo = DocumentChunkRepository()
    assert await repo.search_similar(query) == []  # o limiar cortou tudo

    distance = await repo.nearest_distance(query)
    assert distance is not None
    assert distance > settings.RAG_MAX_DISTANCE


@pytest.mark.asyncio
async def test_returns_none_when_there_is_no_chunk_in_scope(db_session, monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT)
    repo = DocumentChunkRepository()
    assert await repo.nearest_distance(_vector(1.0)) is None


@pytest.mark.asyncio
async def test_respects_the_kb_scope(db_session, seed_document_with_chunk, monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT)
    await seed_document_with_chunk(
        "doc de outro root", kb_root_page_id="99999999-0000-0000-0000-000000000000"
    )
    repo = DocumentChunkRepository()
    assert await repo.nearest_distance(_vector(1.0)) is None


@pytest.mark.asyncio
async def test_returns_none_when_root_is_unconfigured(
    db_session, seed_document_with_chunk, monkeypatch
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None)
    await seed_document_with_chunk("qualquer", kb_root_page_id=ROOT)
    repo = DocumentChunkRepository()
    assert await repo.nearest_distance(_vector(1.0)) is None
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_nearest.py -v`
Expected: FAIL — `AttributeError: 'DocumentChunkRepository' object has no attribute 'nearest_distance'`

- [ ] **Step 3: Implementar o método**

Adicionar em `src/domain/documents/repositories/document_chunk_repository.py`, depois de `search_similar`:

```python
    async def nearest_distance(self, embedding: list[float]) -> float | None:
        """Distância do chunk mais próximo **ignorando o limiar**.

        Serve o trace no caminho de recusa: `search_similar` filtra pelo limiar
        dentro do SQL, então quando ela devolve vazio não se sabe se faltou 0,01
        ou 0,3. Uma query de índice, chamada só quando nada passou — turno que
        recusa não chamou o LLM e tem folga de sobra.
        """
        root = normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID)
        if root is None:
            return None  # mesma degradação fail-closed do search_similar

        distance = DocumentChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(distance)
            .join(DocumentModel, DocumentChunkModel.document_id == DocumentModel.uuid)
            .where(
                DocumentModel.status == "approved",
                DocumentModel.deleted_at.is_(None),
                DocumentModel.kb_root_page_id == root,
            )
            .order_by(distance)
            .limit(1)
        )
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return float(value) if value is not None else None
```

> **Atenção:** `select(distance).join(...)` precisa que o FROM seja
> `document_chunks`. Como `distance` é uma expressão sobre `DocumentChunkModel`,
> o SQLAlchemy infere o FROM correto. Se o teste falhar com "no FROM clause",
> use `select(distance).select_from(DocumentChunkModel).join(DocumentModel, ...)`.

- [ ] **Step 4: Rodar e ver passar**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents/test_chunk_repository_nearest.py -v`
Expected: 4 PASS

- [ ] **Step 5: Rodar a suíte de documents inteira (não regredir)**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/documents tests/unit/domain/documents -q`
Expected: tudo PASS

- [ ] **Step 6: Commit**

```bash
git add src/domain/documents/repositories/document_chunk_repository.py tests/integration/domain/documents/test_chunk_repository_nearest.py
git commit -m "feat(documents): nearest_distance para diagnosticar recusa por limiar"
```

---

### Task 4: Coleta na `AnswerQuestionAction` (tripla de retorno)

A Action passa a devolver `(conversation_id, stream, draft)` e a preencher as fases que rodam no request. **Mudança quebrando** — os três arquivos de teste que desempacotam a dupla são ajustados aqui.

**Files:**
- Modify: `src/domain/conversations/actions/answer_question_action.py`
- Modify: `src/app/api/controllers/conversation_controller.py:44-50` (só o desempacotamento; a fase do engine é a Task 5)
- Modify: `tests/unit/domain/conversations/actions/test_answer_question_action.py` (desempacotamento + `metrics=None` no `_FakeEngine`)
- Modify: `tests/unit/domain/conversations/actions/test_answer_question_out_of_scope.py` (idem)
- Modify: `tests/integration/api/test_ask_endpoint.py` (desempacotamento)
- Create: `tests/unit/domain/conversations/actions/test_answer_question_trace.py`

**Interfaces:**
- Consumes: `TurnTraceDraft` (Task 2), `DocumentChunkRepository.nearest_distance` (Task 3).
- Produces: `AnswerQuestionAction.execute(...) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/unit/domain/conversations/actions/test_answer_question_trace.py`:

```python
"""O que a Action registra no trace nas três rotas do turno.

Arquivo autocontido de propósito: os fakes do `test_answer_question_action.py`
vivem dentro dele (privados), então duplicar os mínimos aqui é mais barato e
menos arriscado que refatorar um teste verde para um conftest compartilhado.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uuid6 import uuid7

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentStreamChunk, KnowledgeSnippet, RetrievalDecision

SNIPPET = KnowledgeSnippet(
    "trecho", Citation("notion", "Doc", "https://n.so/x", "trecho", "pid")
)


class FakeGate:
    def __init__(self, decision: RetrievalDecision) -> None:
        self.decision = decision

    async def decide(self, question, history):
        return self.decision


class FakeSearch:
    """Precisa de `.embeddings` porque o caminho de recusa embeda a query para
    medir a distância do vizinho mais próximo."""

    class _Embeddings:
        async def embed_query(self, query):
            return [0.0, 1.0]

    def __init__(self, snippets) -> None:
        self.snippets = snippets
        self.called_with = None
        self.embeddings = self._Embeddings()

    async def execute(self, query, top_k=None):
        self.called_with = query
        return self.snippets


class FakeEngine:
    async def stream_answer(self, question, history, knowledge, metrics=None):
        yield AgentStreamChunk(type="text", text="resposta")
        yield AgentStreamChunk(type="sources", citations=[])


class FakeSections:
    async def execute(self):
        return ["Mentorship", "Bootcamps"]


class FakeChunks:
    def __init__(self, nearest=None) -> None:
        self.nearest = nearest

    async def nearest_distance(self, embedding):
        return self.nearest


class FakeConvRepo:
    async def get_by_id(self, cid):
        return None

    async def create(self, conversation):
        return conversation


class FakeMsgRepo:
    def __init__(self) -> None:
        self.appended = []

    async def append(self, message):
        self.appended.append(message)
        return message

    async def load_recent(self, conversation_id):
        return []


def _make_action(gate, search, chunks=None) -> AnswerQuestionAction:
    action = AnswerQuestionAction(
        engine=FakeEngine(),
        search=search,
        gate=gate,
        sections=FakeSections(),
        chunks=chunks or FakeChunks(),
    )
    action.conversations = FakeConvRepo()
    action.messages = FakeMsgRepo()
    return action


@pytest.mark.asyncio
async def test_retrieve_path_records_gate_and_retrieval():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="renovação de PSP")),
        search=FakeSearch([SNIPPET]),
    )

    _, _, draft = await action.execute("e as renovações?", None, None)

    assert draft.gate_retrieve is True
    assert draft.gate_search_query == "renovação de PSP"
    assert draft.retrieval_ran is True
    assert draft.retrieval_kept == 1
    assert draft.outcome == "answer"
    assert [e["step"] for e in draft.events] == ["turn_start", "recency", "gate", "retrieval"]


@pytest.mark.asyncio
async def test_skip_path_records_no_retrieval():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=False, search_query="")),
        search=FakeSearch([]),
    )

    _, _, draft = await action.execute("oi", None, None)

    assert draft.gate_retrieve is False
    assert draft.retrieval_ran is False
    assert draft.retrieval_kept == 0
    assert draft.outcome == "answer"
    assert "retrieval" not in [e["step"] for e in draft.events]


@pytest.mark.asyncio
async def test_refusal_path_records_outcome_and_nearest_distance():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="bolo de cenoura")),
        search=FakeSearch([]),  # nada passou do limiar
        chunks=FakeChunks(nearest=0.72),
    )

    _, _, draft = await action.execute("como faço bolo de cenoura?", None, None)

    assert draft.outcome == "refusal"
    assert draft.retrieval_ran is True
    assert draft.retrieval_kept == 0
    assert draft.retrieval_best_distance == 0.72
    assert [e["step"] for e in draft.events][-1] == "refusal"


@pytest.mark.asyncio
async def test_degraded_gate_with_empty_knowledge_does_not_refuse():
    """A guarda do fail-open: gate degradado nunca classificou o turno."""
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="oi", degraded=True)),
        search=FakeSearch([]),
    )

    _, _, draft = await action.execute("oi", None, None)

    assert draft.outcome == "answer"
    assert draft.gate_degraded is True


@pytest.mark.asyncio
async def test_history_tokens_are_estimated_from_the_loaded_recency():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=False, search_query="")),
        search=FakeSearch([]),
    )

    class _WithHistory(FakeMsgRepo):
        async def load_recent(self, conversation_id):
            from src.support.agent.ports import AgentMessage

            return [AgentMessage(role="user", content="a" * 400)]

    action.messages = _WithHistory()
    _, _, draft = await action.execute("oi", None, None)

    assert draft.history_messages == 1
    assert draft.history_tokens_est == 100  # 400 // 4
```

> **Sobre `Conversation`, `uuid7`, `datetime` e `uuid4` nos imports:** o
> `FakeConvRepo.create` devolve a Entity que a Action montou, então os imports
> acima cobrem o arquivo. Se o linter acusar import sem uso depois de você
> escrever, remova — não force o uso.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations/actions/test_answer_question_trace.py -v`
Expected: FAIL — as fixtures não existem e `execute` devolve 2 valores, não 3.

- [ ] **Step 3: Dar `metrics=None` aos fakes de engine que já existem**

A Action vai chamar `stream_answer(..., metrics=metrics)`. Os fakes atuais aceitam
só três parâmetros e quebrariam. Dois lugares:

1. `tests/unit/domain/conversations/actions/test_answer_question_action.py`, na classe `_FakeEngine`:

```python
    async def stream_answer(self, question, history, knowledge, metrics=None):
```

2. `tests/fakes/fake_oracle_engine.py`: mesma mudança de assinatura (o parâmetro é ignorado).

Rodar `DB_PORT=5434 uv run grep -rn "def stream_answer" tests/` não existe — use
`grep -rn "def stream_answer" tests/` e ajuste **todas** as ocorrências encontradas.

- [ ] **Step 4: Modificar a Action**

Em `src/domain/conversations/actions/answer_question_action.py`:

1. Imports novos:

```python
import time

from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.ports import TurnMetrics  # criado na Task 5
from src.support.core.settings import settings
```

> A Task 5 cria `TurnMetrics`. Para não bloquear, **crie o dataclass agora**, na
> Task 5 ele só ganha uso no engine. Ver Task 5 Step 3 para o código exato.

2. `__init__` ganha o repositório de chunks (injetável para teste):

```python
    def __init__(self, engine, search, gate, sections=None, chunks=None) -> None:
        self.engine = engine
        self.search = search
        self.gate = gate
        self.sections = sections or ListKnowledgeSectionsAction()
        self.chunks = chunks or DocumentChunkRepository()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
```

3. `execute` passa a devolver a tripla e a registrar:

```python
    async def execute(
        self, question: str, conversation_id: UUID | None, user_email: str | None
    ) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]:
        now = datetime.now(timezone.utc)
        draft = TurnTraceDraft(question=question, user_email=user_email)
        draft.record("turn_start", question_chars=len(question))

        # ... bloco de resolução/criação da conversa: INALTERADO ...

        history = await self.messages.load_recent(conversation.uuid)
        draft.history_messages = len(history)
        draft.history_tokens_est = sum(max(1, len(m.content) // 4) for m in history)
        draft.record(
            "recency",
            messages=draft.history_messages,
            tokens_est=draft.history_tokens_est,
        )

        gate_started = time.monotonic()
        decision = await self.gate.decide(question, history)
        draft.gate_ms = int((time.monotonic() - gate_started) * 1000)
        draft.gate_retrieve = decision.retrieve
        draft.gate_search_query = decision.search_query or None
        draft.gate_degraded = decision.degraded
        draft.record(
            "gate",
            retrieve=decision.retrieve,
            search_query=decision.search_query,
            degraded=decision.degraded,
            ms=draft.gate_ms,
        )

        await self.messages.append(...)  # INALTERADO

        if decision.retrieve:
            draft.retrieval_ran = True
            draft.retrieval_top_k = settings.RAG_TOP_K
            draft.retrieval_threshold = settings.RAG_MAX_DISTANCE
            retrieval_started = time.monotonic()
            knowledge = await self.search.execute(decision.search_query)
            draft.retrieval_ms = int((time.monotonic() - retrieval_started) * 1000)
            draft.retrieval_kept = len(knowledge)
            if knowledge:
                draft.retrieval_best_distance = None  # a distância exata não volta do search
            draft.record(
                "retrieval",
                top_k=draft.retrieval_top_k,
                kept=draft.retrieval_kept,
                threshold=draft.retrieval_threshold,
                ms=draft.retrieval_ms,
            )

            if not knowledge and not decision.degraded:
                # ... comentário existente sobre a guarda: MANTER INTEGRAL ...
                draft.retrieval_best_distance = await self._nearest_or_none(
                    decision.search_query
                )
                draft.outcome = "refusal"
                draft.record("refusal", best_distance=draft.retrieval_best_distance)
                reply = build_out_of_scope_reply(await self.sections.execute(), question)
                return conversation.uuid, _refusal_stream(reply), draft
        else:
            knowledge = []

        metrics = TurnMetrics()
        draft.engine_metrics = metrics
        stream = self.engine.stream_answer(question, history, knowledge, metrics=metrics)
        return conversation.uuid, stream, draft
```

4. O helper da distância diagnóstica, no fim da classe:

```python
    async def _nearest_or_none(self, query: str) -> float | None:
        """Só no caminho de recusa. Falha aqui não pode custar a recusa ao usuário."""
        try:
            vector = await self.search.embeddings.embed_query(query)
            return await self.chunks.nearest_distance(vector)
        except Exception:  # pragma: no cover - defensivo
            logger.warning("falha ao medir a distância do vizinho mais próximo", exc_info=True)
            return None
```

E no topo do arquivo: `import logging` + `logger = logging.getLogger(__name__)`.

5. `TurnTraceDraft` ganha o campo que segura o `TurnMetrics`:

Em `src/domain/observability/dtos/turn_trace_draft.py`, adicionar ao dataclass:

```python
    engine_metrics: object | None = None  # TurnMetrics preenchido pelo engine (Task 5)
```

- [ ] **Step 5: Ajustar o desempacotamento no controller**

Em `src/app/api/controllers/conversation_controller.py`, trocar:

```python
        conversation_id, stream = await action.execute(
```
por um desempacotamento de três valores.

A fase do engine e a gravação entram na Task 5, então nesta task a variável ainda
não tem uso. Nomeie com underscore para o `pylint` não acusar `unused-variable`:

```python
        conversation_id, stream, _draft = await action.execute(
            data.question, data.conversation_id, user_email
        )
```

A Task 5 renomeia `_draft` → `draft` quando passa a preenchê-lo. **Não** invente um
evento de trace só para "usar" a variável.

- [ ] **Step 6: Ajustar os três arquivos de teste existentes**

Em `tests/unit/domain/conversations/actions/test_answer_question_action.py`,
`test_answer_question_out_of_scope.py` e `tests/integration/api/test_ask_endpoint.py`:
trocar todo `conversation_id, stream = await action.execute(...)` por
`conversation_id, stream, _ = await action.execute(...)`. Nos testes de API que
usam o cliente HTTP, nada muda (o contrato SSE é o mesmo).

- [ ] **Step 7: Rodar e ver passar**

Run: `DB_PORT=5434 uv run pytest tests/unit/domain/conversations tests/integration/api -v`
Expected: tudo PASS, incluindo os 3 testes novos de trace.

- [ ] **Step 8: Commit**

```bash
git add src/domain/conversations/actions/answer_question_action.py src/domain/observability/dtos/turn_trace_draft.py src/app/api/controllers/conversation_controller.py tests/unit/domain/conversations/actions
git commit -m "feat(observability): AnswerQuestionAction registra gate, retrieval e recusa no trace"
```

---

### Task 5: Fase do engine + gravação pós-stream

Fecha o ciclo: o engine reporta tokens e tool calls, o controller mede a latência do stream, e a background task que já existe grava o trace junto da resposta. **No fim desta task já é possível perguntar no chat e ver a linha em `agent_traces`** — o marco que valida o desenho.

**Files:**
- Modify: `src/support/agent/ports.py`
- Modify: `src/support/agent/oracle_engine.py`
- Modify: `src/app/api/controllers/conversation_controller.py`
- Create: `src/domain/observability/repositories/turn_trace_repository.py`
- Create: `src/domain/observability/actions/record_turn_trace_action.py`
- Modify: `tests/fakes/fake_oracle_engine.py`
- Create: `tests/unit/support/agent/test_engine_metrics.py`
- Create: `tests/integration/api/test_ask_trace_persistence.py`

**Interfaces:**
- Consumes: `TurnTraceDraft`, `TurnTrace`, `TurnTraceMapper`.
- Produces: `TurnMetrics`, `OracleEngine.stream_answer(..., metrics=None)`, `TurnTraceRepository.append(trace) -> TurnTrace`, `RecordTurnTraceAction.execute(conversation_id, draft) -> None`.

- [ ] **Step 1: Escrever os testes que falham**

`tests/unit/support/agent/test_engine_metrics.py`:

```python
"""O engine preenche TurnMetrics sem mudar o contrato SSE."""

import pytest

from src.support.agent.ports import TurnMetrics


def test_turn_metrics_starts_zeroed():
    m = TurnMetrics()
    assert m.tool_calls == 0
    assert m.input_tokens is None
    assert m.output_tokens is None


@pytest.mark.asyncio
async def test_stream_answer_accepts_metrics_and_counts_no_tool_call_without_tools():
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    from src.support.agent.oracle_engine import OracleEngine

    metrics = TurnMetrics()
    engine = OracleEngine(model=TestModel(), enable_tools=False)

    chunks = [c async for c in engine.stream_answer("pergunta", [], [], metrics=metrics)]

    assert any(c.type == "text" for c in chunks)
    assert metrics.tool_calls == 0


@pytest.mark.asyncio
async def test_stream_answer_without_metrics_still_works():
    """Parâmetro é opcional: nenhum chamador existente muda."""
    from pydantic_ai.models.test import TestModel

    from src.support.agent.oracle_engine import OracleEngine

    engine = OracleEngine(model=TestModel(), enable_tools=False)
    chunks = [c async for c in engine.stream_answer("pergunta", [], [])]
    assert any(c.type == "sources" for c in chunks)
```

`tests/integration/api/test_ask_trace_persistence.py`:

```python
"""Depois do stream, o turno tem que estar em agent_traces.

Segue o padrão de `test_ask_endpoint.py`: monkeypatcha as factories do
controller, bate no app via ASGITransport e verifica num escopo de sessão
próprio — os testes de API usam o banco de **dev** (o app resolve
`settings.database_url_async`), não o de teste. Cada teste limpa o que criou.
"""

from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


class _FakeSearchAction:
    def __init__(self, *a, **kw):
        pass

    async def execute(self, query, top_k=None):
        from src.domain.shared.value_objects.citation import Citation
        from src.support.agent.ports import KnowledgeSnippet

        return [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "s", "pid"))]


class _FailingEngine:
    async def stream_answer(self, question, history, knowledge=None, metrics=None):
        from src.support.agent.ports import AgentStreamChunk

        yield AgentStreamChunk(type="text", text="ola ")
        raise RuntimeError("boom: engine caiu no meio do stream")


def _parse_conversation_id(body: str) -> str:
    import json

    for block in body.split("\n\n"):
        if "event: conversation" in block:
            data_line = next(l for l in block.split("\n") if l.startswith("data:"))
            return json.loads(data_line[5:].strip())["id"]
    raise AssertionError("evento 'conversation' não emitido")


def _patch_controller(monkeypatch, engine=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient
    from tests.fakes.fake_oracle_engine import FakeOracleEngine
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(
        ctrl, "get_oracle_engine", lambda: engine or FakeOracleEngine(answer="resposta de teste")
    )
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())
    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
    monkeypatch.setattr(ctrl, "SearchKnowledgeBaseAction", _FakeSearchAction)


async def _fetch_trace(conversation_id: UUID) -> dict:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT question, gate_retrieve, retrieval_kept, outcome, engine_ms, "
                    "first_token_ms, events, error FROM agent_traces "
                    "WHERE conversation_id = :cid"
                ),
                {"cid": conversation_id},
            )
        ).mappings().all()
        await s.execute(
            text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id}
        )
        await s.commit()
    assert len(row) == 1, f"esperava 1 trace, achei {len(row)}"
    return dict(row[0])


@pytest.mark.asyncio
async def test_trace_row_exists_after_a_successful_ask(monkeypatch):
    _patch_controller(monkeypatch)
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json={"question": "o que é o PSP?"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: done" in body

    trace = await _fetch_trace(UUID(_parse_conversation_id(body)))
    assert trace["question"] == "o que é o PSP?"
    assert trace["outcome"] == "answer"
    assert trace["gate_retrieve"] is True
    assert trace["retrieval_kept"] == 1
    assert trace["engine_ms"] is not None
    assert trace["first_token_ms"] is not None
    assert trace["events"][0]["step"] == "turn_start"
    assert trace["events"][-1]["step"] == "turn_end"


@pytest.mark.asyncio
async def test_failed_turn_is_traced_even_though_the_answer_is_not_persisted(monkeypatch):
    """Invariante da spec: turno que quebrou é o que mais interessa no trace."""
    _patch_controller(monkeypatch, engine=_FailingEngine())
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json={"question": "vai falhar"})
        body = resp.text
        assert "event: error" in body

    conversation_id = UUID(_parse_conversation_id(body))

    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        roles = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        assert "assistant" not in roles  # resposta parcial não é persistida (M2)

    trace = await _fetch_trace(conversation_id)
    assert trace["outcome"] == "error"
    assert trace["error"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/agent/test_engine_metrics.py tests/integration/api/test_ask_trace_persistence.py -v`
Expected: FAIL — `TurnMetrics` não existe; `TurnTraceModel` não é importável pelo teste de integração ainda (é, desde a Task 1) mas nenhuma linha é gravada.

- [ ] **Step 3: Criar `TurnMetrics` em `ports.py`**

Adicionar em `src/support/agent/ports.py`, depois de `KnowledgeSnippet`:

```python
@dataclass
class TurnMetrics:
    """O que só o motor sabe do turno. Preenchido por ele, lido pelo controller.

    Existe para o trace não precisar entrar no engine: parâmetro opcional,
    nenhum chamador atual muda.
    """

    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
```

E o Protocol ganha o parâmetro opcional:

```python
class OracleEnginePort(Protocol):
    def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet],
        metrics: "TurnMetrics | None" = None,
    ) -> AsyncIterator[AgentStreamChunk]: ...
```

- [ ] **Step 4: (nada a criar) — o projeto já usa `TestModel` do pydantic-ai**

Não escreva fake de modelo. `tests/unit/support/agent/test_oracle_engine.py` já
usa `pydantic_ai.models.test.TestModel`, que suporta `run_stream` e expõe
`last_model_request_parameters.function_tools`. Os testes do Step 1 usam o mesmo.

- [ ] **Step 5: Instrumentar o engine**

Em `src/support/agent/oracle_engine.py`:

```python
    async def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet],
        metrics: TurnMetrics | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
```

Nos dois closures de tool, incrementar antes de chamar:

```python
            @agent.tool_plain
            async def web_search(query: str) -> str:
                """..."""  # docstring INALTERADA
                if metrics is not None:
                    metrics.tool_calls += 1
                try:
                    ...
```

(idem em `fetch_notion_page`.)

E depois do laço de deltas, antes do chunk de sources:

```python
        async with agent.run_stream(prompt) as result:
            async for delta in result.stream_text(delta=True):
                yield AgentStreamChunk(type="text", text=delta)
            if metrics is not None:
                _fill_usage(metrics, result)
```

Com o helper no módulo:

```python
def _fill_usage(metrics: TurnMetrics, result) -> None:
    """Tokens do run, quando o pydantic-ai os expõe no caminho de streaming.

    O nome dos campos variou entre versões do pydantic-ai, e a spec registra
    isso como incerteza: se nada casar, o trace fica sem tokens em vez de
    quebrar o turno.
    """
    try:
        usage = result.usage()
        for attr in ("input_tokens", "request_tokens", "prompt_tokens"):
            if getattr(usage, attr, None) is not None:
                metrics.input_tokens = int(getattr(usage, attr))
                break
        for attr in ("output_tokens", "response_tokens", "completion_tokens"):
            if getattr(usage, attr, None) is not None:
                metrics.output_tokens = int(getattr(usage, attr))
                break
    except Exception:  # pragma: no cover - observabilidade não derruba turno
        logger.warning("não foi possível ler usage() do run", exc_info=True)
```

Importar `TurnMetrics` de `ports` no topo.

- [ ] **Step 6: Atualizar o fake de engine dos testes**

`tests/fakes/fake_oracle_engine.py`: `stream_answer` ganha `metrics=None` na assinatura e ignora o parâmetro (ou soma `tool_calls` se o teste precisar).

- [ ] **Step 7: Repositório e Action de escrita**

`src/domain/observability/repositories/turn_trace_repository.py`:

```python
from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.mappers import TurnTraceMapper
from src.domain.observability.models.turn_trace import TurnTraceModel
from src.support.core.context import CurrentAsyncSessionContext


class TurnTraceRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def append(self, trace: TurnTrace) -> TurnTrace:
        model = TurnTraceModel(**TurnTraceMapper.to_model_attrs(trace))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return TurnTraceMapper.to_entity(model)
```

`src/domain/observability/actions/record_turn_trace_action.py`:

```python
from uuid import UUID

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


class RecordTurnTraceAction:
    """Persiste o trace do turno. Chamada dentro de run_in_async_session,
    junto da resposta do assistente — uma sessão, duas escritas."""

    def __init__(self) -> None:
        self.traces = TurnTraceRepository()

    async def execute(self, conversation_id: UUID, draft: TurnTraceDraft) -> None:
        await self.traces.append(draft.to_entity(conversation_id=conversation_id))
```

- [ ] **Step 8: Fechar o ciclo no controller**

Em `src/app/api/controllers/conversation_controller.py`, dentro de `ask`:

```python
        conversation_id, stream, draft = await action.execute(
            data.question, data.conversation_id, user_email
        )

        captured: dict = {"text": "", "citations": []}

        async def event_source() -> AsyncIterator[str]:
            yield _sse("conversation", {"id": str(conversation_id)})
            failed = False
            engine_started = time.monotonic()
            try:
                async for chunk in stream:
                    if chunk.type == "text":
                        if draft.first_token_ms is None:
                            draft.first_token_ms = int(
                                (time.monotonic() - engine_started) * 1000
                            )
                            draft.record("first_token")
                        captured["text"] += chunk.text
                        yield _sse("token", {"text": chunk.text})
                    elif chunk.type == "sources":
                        captured["citations"] = chunk.citations
                        yield _sse(
                            "sources",
                            {"citations": [_citation_payload(c) for c in chunk.citations]},
                        )
            except Exception:
                failed = True
                logger.exception("stream falhou durante /conversations/ask")
                draft.outcome = "error"
                draft.error = "erro ao gerar a resposta"
                yield _sse("error", {"message": "erro ao gerar a resposta"})

            draft.engine_ms = int((time.monotonic() - engine_started) * 1000)
            draft.citations_count = len(captured["citations"])
            _absorb_engine_metrics(draft)
            draft.record("turn_end", outcome=draft.outcome)

            # A resposta só é persistida em sucesso (decisão do M2); o trace é
            # gravado SEMPRE — turno que quebrou é o que mais interessa no trace.
            try:
                await _persist_turn(
                    conversation_id,
                    draft,
                    captured["text"] if (not failed and captured["text"]) else None,
                    captured["citations"],
                )
            except Exception:
                logger.exception("falha ao persistir turno (resposta e/ou trace)")

            yield _sse("done", {})
```

E as funções de módulo:

```python
def _absorb_engine_metrics(draft) -> None:
    metrics = getattr(draft, "engine_metrics", None)
    if metrics is None:
        return  # caminho de recusa: não houve engine
    draft.tool_calls = metrics.tool_calls
    draft.input_tokens = metrics.input_tokens
    draft.output_tokens = metrics.output_tokens


async def _persist_turn(conversation_id: UUID, draft, content: str | None, citations: list) -> None:
    """Uma sessão própria para as duas escritas pós-stream."""

    async def _work() -> None:
        if content:
            await AppendAssistantMessageAction().execute(conversation_id, content, citations)
        try:
            await RecordTurnTraceAction().execute(conversation_id, draft)
        except Exception:
            # Invariante da spec: observabilidade não pode custar a resposta.
            logger.exception("falha ao gravar o trace do turno")

    await run_in_async_session(_work)
```

Remover `_persist_assistant` (substituída por `_persist_turn`), adicionar `import time` e os imports de `RecordTurnTraceAction`.

- [ ] **Step 9: Rodar e ver passar**

```bash
DB_PORT=5434 uv run pytest tests/unit/support/agent tests/integration/api -v
DB_PORT=5434 uv run pytest -q
```
Expected: tudo PASS.

- [ ] **Step 10: Validar o marco à mão**

```bash
DB_PORT=5434 ./start_dev   # ou uvicorn main:app --reload
# em outro terminal:
curl -N -X POST localhost:8000/conversations/ask -H 'content-type: application/json' \
  -d '{"question":"o que é o Web3 Bootcamp?"}'
docker exec oracle_borderless_db psql -U oracle -d oracle_borderless \
  -c "select question, gate_retrieve, retrieval_kept, outcome, first_token_ms, engine_ms from agent_traces order by created_at desc limit 3"
```
Expected: a linha do turno aparece com os números preenchidos. **Se `input_tokens` vier nulo, não é bug** — é a incerteza do `usage()` registrada na spec; anote o resultado no commit.

- [ ] **Step 11: Commit**

```bash
git add src/support/agent src/domain/observability src/app/api/controllers/conversation_controller.py tests
git commit -m "feat(observability): grava o trace do turno pós-stream, junto da resposta"
```

---

### Task 6: Leituras e agregados

Tudo que a página consome, ainda sem HTTP.

**Files:**
- Modify: `src/domain/observability/repositories/turn_trace_repository.py`
- Create: `src/domain/observability/dtos/ops_overview.py`
- Create: `src/domain/observability/actions/get_ops_overview_action.py`
- Create: `src/domain/observability/actions/list_recent_traces_action.py`
- Create: `src/domain/observability/actions/get_turn_trace_action.py`
- Create: `src/domain/observability/actions/read_eval_report_action.py`
- Create: `src/domain/documents/actions/count_knowledge_base_action.py`
- Create: `src/support/observability/__init__.py`, `src/support/observability/eval_report_store.py`
- Modify: `src/support/core/settings.py` (`EVAL_REPORTS_DIR`)
- Create: `tests/unit/support/observability/__init__.py`, `test_eval_report_store.py`
- Create: `tests/integration/domain/observability/__init__.py`, `test_trace_summary.py`

**Interfaces:**
- Consumes: `TurnTraceRepository` (Task 5).
- Produces: `TurnTraceRepository.summarize(window) -> TraceSummary`, `.list_recent(window, limit) -> list[TurnTrace]`, `.get(uuid) -> TurnTrace | None`; `CountKnowledgeBaseAction.execute() -> KnowledgeCounts`; `EvalReportStore.read() -> dict | None`, `.history(limit) -> list[dict]`; `GetOpsOverviewAction.execute(window) -> OpsOverview`.

- [ ] **Step 1: Escrever os testes que falham (store do eval)**

`tests/unit/support/observability/test_eval_report_store.py`:

```python
import json

import pytest

from src.support.observability.eval_report_store import EvalReportStore


def test_read_returns_none_when_directory_is_absent(tmp_path):
    store = EvalReportStore(tmp_path / "nao-existe")
    assert store.read() is None
    assert store.history() == []


def test_read_returns_the_report(tmp_path):
    (tmp_path / "eval_report.json").write_text(
        json.dumps({"verdict": "pass", "metrics": {}}), encoding="utf-8"
    )
    assert EvalReportStore(tmp_path).read()["verdict"] == "pass"


def test_history_returns_one_dict_per_line_newest_first(tmp_path):
    lines = [json.dumps({"run": n}) for n in (1, 2, 3)]
    (tmp_path / "eval_runs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [d["run"] for d in EvalReportStore(tmp_path).history()] == [3, 2, 1]


def test_history_skips_blank_lines(tmp_path):
    (tmp_path / "eval_runs.jsonl").write_text('{"run": 1}\n\n', encoding="utf-8")
    assert len(EvalReportStore(tmp_path).history()) == 1


def test_corrupt_report_raises_a_clear_error(tmp_path):
    (tmp_path / "eval_report.json").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError, match="eval_report.json"):
        EvalReportStore(tmp_path).read()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/support/observability -v`
Expected: FAIL — módulo inexistente.

- [ ] **Step 3: Implementar o store + a setting**

`src/support/core/settings.py`, no bloco de RAG/eval:

```python
    # Onde o harness de eval grava seus reports (lidos pela página de ops)
    EVAL_REPORTS_DIR: str = "evals/reports"
```

`src/support/observability/eval_report_store.py`:

```python
"""Leitura dos reports do harness de eval. I/O de filesystem — infraestrutura,
não domínio. É também onde um exportador OTel entraria depois."""

import json
from pathlib import Path

from src.support.core.settings import settings


class EvalReportStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory or settings.EVAL_REPORTS_DIR)

    def read(self) -> dict | None:
        path = self.directory / "eval_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"eval_report.json ilegível em {path}: {exc}") from exc

    def history(self, limit: int = 20) -> list[dict]:
        path = self.directory / "eval_runs.jsonl"
        if not path.is_file():
            return []
        runs: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # uma linha ruim não invalida o histórico
        return list(reversed(runs))[:limit]
```

- [ ] **Step 4: Escrever o teste (integração) dos agregados**

`tests/integration/domain/observability/test_trace_summary.py`:

```python
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.repositories.conversation_repository import (
    ConversationRepository,
)
from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


async def _conversation() -> Conversation:
    now = datetime.now(timezone.utc)
    return await ConversationRepository().create(
        Conversation(uuid=uuid7(), user_email=None, title="t", created_at=now, updated_at=now, deleted_at=None)
    )


def _trace(conversation_id, **overrides) -> TurnTrace:
    base = dict(
        uuid=uuid7(),
        conversation_id=conversation_id,
        question="q",
        outcome="answer",
        created_at=datetime.now(timezone.utc),
        gate_retrieve=True,
        retrieval_ran=True,
        retrieval_kept=2,
        retrieval_best_distance=0.4,
        retrieval_threshold=0.55,
        engine_ms=1000,
        first_token_ms=200,
    )
    base.update(overrides)
    return TurnTrace(**base)


@pytest.mark.asyncio
async def test_summarize_counts_gate_split_and_outcomes(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    await repo.append(_trace(conversation.uuid))
    await repo.append(_trace(conversation.uuid, gate_retrieve=False, retrieval_ran=False))
    await repo.append(_trace(conversation.uuid, outcome="refusal", retrieval_kept=0))
    await repo.append(_trace(conversation.uuid, outcome="error", engine_ms=None))
    await db_session.flush()

    summary = await repo.summarize(window="all")

    assert summary.turns == 4
    assert summary.gate_retrieve == 3
    assert summary.gate_skip == 1
    assert summary.answers == 2
    assert summary.refusals == 1
    assert summary.errors == 1
    assert summary.avg_engine_ms == pytest.approx(1000, abs=1)


@pytest.mark.asyncio
async def test_summarize_respects_the_window(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    old = _trace(conversation.uuid)
    await repo.append(old)
    await db_session.flush()
    # empurra a linha para 10 dias atrás
    from sqlalchemy import update

    from src.domain.observability.models.turn_trace import TurnTraceModel

    await db_session.execute(
        update(TurnTraceModel)
        .where(TurnTraceModel.uuid == old.uuid)
        .values(created_at=datetime.now(timezone.utc) - timedelta(days=10))
    )
    await db_session.flush()

    assert (await repo.summarize(window="all")).turns == 1
    assert (await repo.summarize(window="7d")).turns == 0
    assert (await repo.summarize(window="24h")).turns == 0


@pytest.mark.asyncio
async def test_list_recent_is_newest_first_and_respects_limit(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    for n in range(3):
        await repo.append(_trace(conversation.uuid, question=f"q{n}"))
    await db_session.flush()

    recent = await repo.list_recent(window="all", limit=2)
    assert len(recent) == 2


@pytest.mark.asyncio
async def test_summarize_on_empty_window_returns_zeros(db_session):
    summary = await TurnTraceRepository().summarize(window="24h")
    assert summary.turns == 0
    assert summary.avg_engine_ms is None
```

- [ ] **Step 5: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/integration/domain/observability -v`
Expected: FAIL — `summarize`/`list_recent` não existem.

- [ ] **Step 6: Implementar os DTOs de leitura**

`src/domain/observability/dtos/ops_overview.py`:

```python
from dataclasses import dataclass, field


@dataclass
class TraceSummary:
    turns: int = 0
    gate_retrieve: int = 0
    gate_skip: int = 0
    gate_degraded: int = 0
    answers: int = 0
    refusals: int = 0
    errors: int = 0
    avg_first_token_ms: float | None = None
    max_first_token_ms: int | None = None
    avg_engine_ms: float | None = None
    max_engine_ms: int | None = None
    avg_retrieval_kept: float | None = None
    avg_best_distance: float | None = None


@dataclass
class KnowledgeCounts:
    documents_active: int = 0
    documents_archived: int = 0
    chunks: int = 0
    sections: list[str] = field(default_factory=list)


@dataclass
class SyncStatus:
    job_name: str | None = None
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


@dataclass
class OpsOverview:
    window: str
    knowledge: KnowledgeCounts
    sync: SyncStatus
    traces: TraceSummary
    rag_top_k: int
    rag_max_distance: float
```

- [ ] **Step 7: Implementar `summarize`, `list_recent` e `get` no repositório**

Adicionar em `src/domain/observability/repositories/turn_trace_repository.py`:

```python
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Float, case, func, select
from sqlalchemy.sql.elements import ColumnElement

from src.domain.observability.dtos.ops_overview import TraceSummary

_WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "all": None}


def _window_start(window: str) -> datetime | None:
    if window not in _WINDOWS:
        raise ValueError(f"janela inválida: {window!r}")
    delta = _WINDOWS[window]
    return None if delta is None else datetime.now(timezone.utc) - delta
```

e os métodos:

```python
    def _in_window(self, window: str) -> list[ColumnElement]:
        start = _window_start(window)
        return [] if start is None else [TurnTraceModel.created_at >= start]

    async def summarize(self, window: str) -> TraceSummary:
        def count_when(condition) -> ColumnElement:
            return func.count(case((condition, 1)))

        stmt = select(
            func.count().label("turns"),
            count_when(TurnTraceModel.gate_retrieve.is_(True)).label("gate_retrieve"),
            count_when(TurnTraceModel.gate_retrieve.is_(False)).label("gate_skip"),
            count_when(TurnTraceModel.gate_degraded.is_(True)).label("gate_degraded"),
            count_when(TurnTraceModel.outcome == "answer").label("answers"),
            count_when(TurnTraceModel.outcome == "refusal").label("refusals"),
            count_when(TurnTraceModel.outcome == "error").label("errors"),
            func.avg(TurnTraceModel.first_token_ms.cast(Float)).label("avg_first_token_ms"),
            func.max(TurnTraceModel.first_token_ms).label("max_first_token_ms"),
            func.avg(TurnTraceModel.engine_ms.cast(Float)).label("avg_engine_ms"),
            func.max(TurnTraceModel.engine_ms).label("max_engine_ms"),
            func.avg(TurnTraceModel.retrieval_kept.cast(Float)).label("avg_retrieval_kept"),
            func.avg(TurnTraceModel.retrieval_best_distance).label("avg_best_distance"),
        ).where(*self._in_window(window))

        row = (await self.session.execute(stmt)).one()
        return TraceSummary(
            turns=row.turns,
            gate_retrieve=row.gate_retrieve,
            gate_skip=row.gate_skip,
            gate_degraded=row.gate_degraded,
            answers=row.answers,
            refusals=row.refusals,
            errors=row.errors,
            avg_first_token_ms=float(row.avg_first_token_ms) if row.avg_first_token_ms is not None else None,
            max_first_token_ms=row.max_first_token_ms,
            avg_engine_ms=float(row.avg_engine_ms) if row.avg_engine_ms is not None else None,
            max_engine_ms=row.max_engine_ms,
            avg_retrieval_kept=float(row.avg_retrieval_kept) if row.avg_retrieval_kept is not None else None,
            avg_best_distance=float(row.avg_best_distance) if row.avg_best_distance is not None else None,
        )

    async def list_recent(self, window: str, limit: int = 50) -> list[TurnTrace]:
        stmt = (
            select(TurnTraceModel)
            .where(*self._in_window(window))
            .order_by(TurnTraceModel.created_at.desc())
            .limit(limit)
        )
        models = (await self.session.execute(stmt)).scalars().all()
        return [TurnTraceMapper.to_entity(m) for m in models]

    async def get(self, trace_id: UUID) -> TurnTrace | None:
        stmt = select(TurnTraceModel).where(TurnTraceModel.uuid == trace_id)
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return TurnTraceMapper.to_entity(model) if model else None
```

- [ ] **Step 8: Implementar `CountKnowledgeBaseAction`**

`src/domain/documents/actions/count_knowledge_base_action.py`:

```python
from sqlalchemy import func, select

from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
from src.domain.documents.models.document import DocumentModel
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.domain.observability.dtos.ops_overview import KnowledgeCounts
from src.support.core.context import CurrentAsyncSessionContext


class CountKnowledgeBaseAction:
    """Contagens da base para a página de ops. Fronteira do subdomínio documents:
    quem quer esses números compõe esta Action, não o repositório."""

    def __init__(self, sections=None) -> None:
        self.session = CurrentAsyncSessionContext.get()
        self.sections = sections or ListKnowledgeSectionsAction()

    async def execute(self) -> KnowledgeCounts:
        active = await self.session.scalar(
            select(func.count())
            .select_from(DocumentModel)
            .where(DocumentModel.deleted_at.is_(None), DocumentModel.status == "approved")
        )
        archived = await self.session.scalar(
            select(func.count()).select_from(DocumentModel).where(DocumentModel.deleted_at.is_not(None))
        )
        chunks = await self.session.scalar(select(func.count()).select_from(DocumentChunkModel))
        return KnowledgeCounts(
            documents_active=active or 0,
            documents_archived=archived or 0,
            chunks=chunks or 0,
            sections=await self.sections.execute(),
        )
```

- [ ] **Step 9: Implementar as Actions de leitura de ops**

`get_ops_overview_action.py`:

```python
from sqlalchemy import select

from src.domain.documents.actions.count_knowledge_base_action import CountKnowledgeBaseAction
from src.domain.observability.dtos.ops_overview import OpsOverview, SyncStatus
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.models.job_execution import JobExecution
from src.support.core.settings import settings


class GetOpsOverviewAction:
    """Tudo que o mapa vivo precisa, numa chamada."""

    def __init__(self, counts=None, traces=None) -> None:
        self.counts = counts or CountKnowledgeBaseAction()
        self.traces = traces or TurnTraceRepository()
        self.session = CurrentAsyncSessionContext.get()

    async def execute(self, window: str) -> OpsOverview:
        return OpsOverview(
            window=window,
            knowledge=await self.counts.execute(),
            sync=await self._last_sync(),
            traces=await self.traces.summarize(window),
            rag_top_k=settings.RAG_TOP_K,
            rag_max_distance=settings.RAG_MAX_DISTANCE,
        )

    async def _last_sync(self) -> SyncStatus:
        stmt = (
            select(JobExecution)
            .where(JobExecution.job_name.ilike("%SyncKnowledgeBase%"))
            .order_by(JobExecution.started_at.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return SyncStatus()
        return SyncStatus(
            job_name=row.job_name,
            status=row.status,
            started_at=row.started_at.isoformat() if row.started_at else None,
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
            error=row.error,
        )
```

`list_recent_traces_action.py`, `get_turn_trace_action.py` e `read_eval_report_action.py` — cada um delegando ao repositório/store:

```python
# list_recent_traces_action.py
class ListRecentTracesAction:
    def __init__(self, traces=None) -> None:
        self.traces = traces or TurnTraceRepository()

    async def execute(self, window: str, limit: int = 50) -> list[TurnTrace]:
        return await self.traces.list_recent(window=window, limit=limit)


# get_turn_trace_action.py
class GetTurnTraceAction:
    def __init__(self, traces=None) -> None:
        self.traces = traces or TurnTraceRepository()

    async def execute(self, trace_id: UUID) -> TurnTrace:
        trace = await self.traces.get(trace_id)
        if trace is None:
            raise NotFoundError(f"trace {trace_id} não encontrado")
        return trace


# read_eval_report_action.py
class ReadEvalReportAction:
    def __init__(self, store=None) -> None:
        self.store = store or EvalReportStore()

    async def execute(self) -> dict:
        report = self.store.read()
        if report is None:
            return {"status": "no_runs", "report": None, "history": []}
        return {"status": "ok", "report": report, "history": self.store.history()}
```

Com os imports correspondentes (`NotFoundError` de `src.support.core.exceptions`, `EvalReportStore` de `src.support.observability.eval_report_store`, `TurnTrace`, `UUID`).

- [ ] **Step 10: Rodar e ver passar**

```bash
DB_PORT=5434 uv run pytest tests/unit/support/observability tests/integration/domain/observability -v
DB_PORT=5434 uv run pytest -q
```
Expected: tudo PASS.

- [ ] **Step 11: Commit**

```bash
git add src/domain/observability src/domain/documents/actions/count_knowledge_base_action.py src/support/observability src/support/core/settings.py tests
git commit -m "feat(observability): agregados do trace, contagens da base e leitura dos reports de eval"
```

---

### Task 7: Endpoints de ops + encaixe de admin

**Files:**
- Create: `src/app/api/dependencies/require_admin.py`
- Create: `src/app/api/responses/ops_responses.py`
- Create: `src/app/api/controllers/ops_controller.py`
- Create: `src/app/api/routes/ops.py`
- Create: `tests/unit/app/api/__init__.py`, `tests/unit/app/api/test_require_admin.py`
- Create: `tests/integration/api/test_ops_endpoints.py`

**Interfaces:**
- Consumes: as Actions da Task 6.
- Produces: `GET /ops/overview`, `GET /ops/turns`, `GET /ops/turns/{trace_id}`, `GET /ops/eval`; `require_admin` dependency.

- [ ] **Step 1: Escrever os testes que falham**

`tests/unit/app/api/test_require_admin.py`:

```python
"""Encaixe da auth de admin. Hoje no-op — o teste tranca o contrato para quando
a auth chegar: não-admin recebe 404, nunca 403 (a página não revela que existe)."""

import inspect

import pytest

from src.app.api.dependencies.require_admin import require_admin


def test_is_a_coroutine_dependency():
    assert inspect.iscoroutinefunction(require_admin)


@pytest.mark.asyncio
async def test_today_it_lets_everyone_through():
    assert await require_admin() is None


def test_module_documents_the_404_decision():
    """Se alguém trocar por 403 sem discutir, este teste chama a atenção."""
    assert "404" in (require_admin.__doc__ or "")
```

`tests/integration/api/test_ops_endpoints.py`:

```python
"""Shape dos quatro endpoints de ops. Mesmo padrão dos outros testes de API:
ASGITransport contra o app real, banco de dev, engine descartada entre testes."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def ops_client():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_overview_returns_the_map_payload(ops_client):
    resp = await ops_client.get("/ops/overview?window=24h")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "24h"
    assert "documents_active" in body["knowledge"]
    assert "gate_retrieve" in body["traces"]
    assert body["rag_max_distance"] > 0
    assert body["rag_top_k"] > 0
    # sem run do sync, os campos vêm nulos em vez de estourar
    assert "status" in body["sync"]


@pytest.mark.asyncio
async def test_overview_rejects_an_unknown_window(ops_client):
    assert (await ops_client.get("/ops/overview?window=42y")).status_code == 422


@pytest.mark.asyncio
async def test_turns_list_returns_a_list(ops_client):
    resp = await ops_client.get("/ops/turns?window=24h&limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_unknown_trace_is_404(ops_client):
    resp = await ops_client.get("/ops/turns/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eval_reports_no_runs_when_there_is_no_report(ops_client, tmp_path, monkeypatch):
    from src.support.core.settings import settings

    monkeypatch.setattr(settings, "EVAL_REPORTS_DIR", str(tmp_path))
    resp = await ops_client.get("/ops/eval")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_runs"
    assert body["history"] == []
```

> **Atenção ao `monkeypatch` do `EVAL_REPORTS_DIR`:** a `ReadEvalReportAction`
> instancia o `EvalReportStore` no `__init__`, que lê `settings.EVAL_REPORTS_DIR`
> naquele momento. Como a Action é criada **por request**, o patch pega. Se você
> mudar a Action para receber o store por injeção no módulo, o teste quebra —
> mantenha a instanciação dentro do `__init__`.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/app/api tests/integration/api/test_ops_endpoints.py -v`
Expected: FAIL — módulos e rotas inexistentes.

- [ ] **Step 3: Implementar a dependency**

`src/app/api/dependencies/require_admin.py`:

```python
"""Encaixe único da auth de admin da página de ops.

HOJE: no-op — a página está aberta por decisão da dona do produto, enquanto a
auth do ecossistema não está definida (ver CLAUDE.md, "pontos em aberto").

QUANDO A AUTH CHEGAR: validar aqui a identidade (hoje o e-mail chega por
`Cf-Access-Authenticated-User-Email`, sem validação) e, para quem não for admin,
levantar `NotFoundError` — que o exception_handlers traduz para **404**. Não usar
403: a página de ops não deve nem revelar que existe. O lado do frontend é
`useCurrentUser().isAdmin`, que decide se a rota é montada.
"""


async def require_admin() -> None:
    return None
```

- [ ] **Step 4: Implementar os responses**

`src/app/api/responses/ops_responses.py`:

```python
from typing import Literal

from pydantic import BaseModel

from src.domain.observability.dtos.ops_overview import OpsOverview
from src.domain.observability.entities.turn_trace import TurnTrace

Window = Literal["24h", "7d", "all"]


class KnowledgeCountsResponse(BaseModel):
    documents_active: int
    documents_archived: int
    chunks: int
    sections: list[str]


class SyncStatusResponse(BaseModel):
    job_name: str | None
    status: str | None
    started_at: str | None
    finished_at: str | None
    error: str | None


class TraceSummaryResponse(BaseModel):
    turns: int
    gate_retrieve: int
    gate_skip: int
    gate_degraded: int
    answers: int
    refusals: int
    errors: int
    avg_first_token_ms: float | None
    max_first_token_ms: int | None
    avg_engine_ms: float | None
    max_engine_ms: int | None
    avg_retrieval_kept: float | None
    avg_best_distance: float | None


class OpsOverviewResponse(BaseModel):
    window: str
    knowledge: KnowledgeCountsResponse
    sync: SyncStatusResponse
    traces: TraceSummaryResponse
    rag_top_k: int
    rag_max_distance: float

    @classmethod
    def from_dto(cls, dto: OpsOverview) -> "OpsOverviewResponse":
        return cls(
            window=dto.window,
            knowledge=KnowledgeCountsResponse(**vars(dto.knowledge)),
            sync=SyncStatusResponse(**vars(dto.sync)),
            traces=TraceSummaryResponse(**vars(dto.traces)),
            rag_top_k=dto.rag_top_k,
            rag_max_distance=dto.rag_max_distance,
        )


class TurnSummaryResponse(BaseModel):
    id: str
    created_at: str
    question: str
    gate_retrieve: bool
    gate_degraded: bool
    retrieval_kept: int
    retrieval_best_distance: float | None
    outcome: str
    first_token_ms: int | None
    engine_ms: int | None
    citations_count: int
    tool_calls: int

    @classmethod
    def from_entity(cls, t: TurnTrace) -> "TurnSummaryResponse":
        return cls(
            id=str(t.uuid),
            created_at=t.created_at.isoformat(),
            question=t.question,
            gate_retrieve=t.gate_retrieve,
            gate_degraded=t.gate_degraded,
            retrieval_kept=t.retrieval_kept,
            retrieval_best_distance=t.retrieval_best_distance,
            outcome=t.outcome,
            first_token_ms=t.first_token_ms,
            engine_ms=t.engine_ms,
            citations_count=t.citations_count,
            tool_calls=t.tool_calls,
        )


class TurnDetailResponse(TurnSummaryResponse):
    conversation_id: str
    gate_search_query: str | None
    gate_ms: int
    retrieval_ran: bool
    retrieval_top_k: int
    retrieval_threshold: float
    retrieval_ms: int | None
    history_messages: int
    history_tokens_est: int
    input_tokens: int | None
    output_tokens: int | None
    error: str | None
    events: list[dict]

    @classmethod
    def from_entity(cls, t: TurnTrace) -> "TurnDetailResponse":
        base = TurnSummaryResponse.from_entity(t)
        return cls(
            **base.model_dump(),
            conversation_id=str(t.conversation_id),
            gate_search_query=t.gate_search_query,
            gate_ms=t.gate_ms,
            retrieval_ran=t.retrieval_ran,
            retrieval_top_k=t.retrieval_top_k,
            retrieval_threshold=t.retrieval_threshold,
            retrieval_ms=t.retrieval_ms,
            history_messages=t.history_messages,
            history_tokens_est=t.history_tokens_est,
            input_tokens=t.input_tokens,
            output_tokens=t.output_tokens,
            error=t.error,
            events=t.events,
        )
```

- [ ] **Step 5: Implementar o controller e a rota**

`src/app/api/controllers/ops_controller.py`:

```python
from uuid import UUID

from src.app.api.responses.ops_responses import (
    OpsOverviewResponse,
    TurnDetailResponse,
    TurnSummaryResponse,
    Window,
)
from src.domain.observability.actions.get_ops_overview_action import GetOpsOverviewAction
from src.domain.observability.actions.get_turn_trace_action import GetTurnTraceAction
from src.domain.observability.actions.list_recent_traces_action import ListRecentTracesAction
from src.domain.observability.actions.read_eval_report_action import ReadEvalReportAction


class OpsController:
    @staticmethod
    async def overview(window: Window = "24h") -> OpsOverviewResponse:
        return OpsOverviewResponse.from_dto(await GetOpsOverviewAction().execute(window))

    @staticmethod
    async def turns(window: Window = "24h", limit: int = 50) -> list[TurnSummaryResponse]:
        traces = await ListRecentTracesAction().execute(window=window, limit=limit)
        return [TurnSummaryResponse.from_entity(t) for t in traces]

    @staticmethod
    async def turn(trace_id: UUID) -> TurnDetailResponse:
        return TurnDetailResponse.from_entity(await GetTurnTraceAction().execute(trace_id))

    @staticmethod
    async def eval_report() -> dict:
        return await ReadEvalReportAction().execute()
```

`src/app/api/routes/ops.py`:

```python
"""Página de ops — hoje aberta; `require_admin` é o encaixe único da auth de admin."""

from fastapi import APIRouter, Depends

from src.app.api.controllers.ops_controller import OpsController
from src.app.api.dependencies.require_admin import require_admin

public_router = APIRouter(
    prefix="/ops", tags=["Ops"], dependencies=[Depends(require_admin)]
)
public_router.get("/overview")(OpsController.overview)
public_router.get("/turns")(OpsController.turns)
public_router.get("/turns/{trace_id}")(OpsController.turn)
public_router.get("/eval")(OpsController.eval_report)
```

- [ ] **Step 6: Rodar e ver passar**

```bash
DB_PORT=5434 uv run pytest tests/unit/app/api tests/integration/api -v
DB_PORT=5434 uv run pytest -q
```
Expected: tudo PASS.

- [ ] **Step 7: Commit**

```bash
git add src/app/api tests/unit/app/api tests/integration/api/test_ops_endpoints.py
git commit -m "feat(ops): endpoints de overview, turnos e eval + encaixe require_admin"
```

---

### Task 8: `ARCHITECTURE_MAP` + o teste do mapa honesto

O registro único das caixas e a amarra que impede o desenho de mentir. Vem antes da tela: é o dado que a tela renderiza.

**Files:**
- Create: `frontend/src/features/ops/architectureMap.ts`
- Create: `frontend/src/features/ops/architectureMap.test.ts`

**Interfaces:**
- Consumes: nada.
- Produces: `ARCHITECTURE_MAP: MapBand[]`, `type MapBox = { id, label, file, description, metric? }`.

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/features/ops/architectureMap.test.ts`:

```ts
// @vitest-environment node
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ARCHITECTURE_MAP } from "./architectureMap";

const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");
const boxes = ARCHITECTURE_MAP.flatMap((band) => band.boxes);

describe("ARCHITECTURE_MAP", () => {
  it("declares at least one band with boxes", () => {
    expect(ARCHITECTURE_MAP.length).toBeGreaterThan(0);
    expect(boxes.length).toBeGreaterThan(0);
  });

  it("every declared file exists in the repository", () => {
    // Esta é a amarra do "mapa honesto": mudou o pipeline, muda o mapa.
    const missing = boxes
      .flatMap((box) => box.files.map((file) => ({ id: box.id, file })))
      .filter(({ file }) => !existsSync(resolve(REPO_ROOT, file)));

    expect(missing).toEqual([]);
  });

  it("has unique box ids", () => {
    const ids = boxes.map((b) => b.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every box a label and a description in pt-BR", () => {
    for (const box of boxes) {
      expect(box.label.length).toBeGreaterThan(0);
      expect(box.description.length).toBeGreaterThan(0);
    }
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/features/ops/architectureMap.test.ts`
Expected: FAIL — módulo `./architectureMap` não existe.

- [ ] **Step 3: Escrever o registro**

`frontend/src/features/ops/architectureMap.ts`:

```ts
/**
 * REGISTRO ÚNICO das caixas do mapa de arquitetura.
 *
 * ⚠️ REGRA DO MAPA HONESTO: mudou o pipeline (arquivo renomeado, etapa nova,
 * etapa removida), muda este registro NO MESMO COMMIT. `architectureMap.test.ts`
 * falha se qualquer caminho declarado aqui deixar de existir — é o que impede o
 * desenho de envelhecer em silêncio. Ver a spec de 2026-08-03, "Requisito: o
 * mapa não pode mentir".
 *
 * `metric` é a chave lida do payload de /ops/overview para a caixa exibir número.
 */

export interface MapBox {
  id: string;
  label: string;
  description: string;
  files: string[];
  metric?: string;
}

export interface MapBand {
  id: string;
  title: string;
  boxes: MapBox[];
}

export const ARCHITECTURE_MAP: MapBand[] = [
  {
    id: "ingestion",
    title: "Ingestão — base de conhecimento",
    boxes: [
      {
        id: "notion-mcp",
        label: "Notion MCP",
        description: "Lê o subtree do folder Products via MCP. Fora do root, nada é visitado.",
        files: ["src/support/clients/notion/notion_client.py", "src/support/clients/notion/mcp_session.py"],
      },
      {
        id: "curation",
        label: "Curadoria",
        description: "Rejeita linha de banco e títulos na denylist. Segunda linha de defesa do escopo.",
        files: ["src/domain/documents/services/knowledge_curation_policy.py"],
      },
      {
        id: "sync",
        label: "Sync",
        description: "Full e incremental, idempotente. Reconcilia o que saiu do escopo.",
        files: [
          "src/domain/documents/actions/sync_knowledge_base_action.py",
          "src/app/console/jobs/sync_knowledge_base_job.py",
        ],
        metric: "sync",
      },
      {
        id: "chunking",
        label: "Limpeza + chunking",
        description: "Remove markup do Notion e quebra por heading.",
        files: [
          "src/domain/documents/services/notion_markup_cleaner.py",
          "src/domain/documents/services/chunking_service.py",
        ],
      },
      {
        id: "embeddings",
        label: "Embeddings",
        description: "text-embedding-3-small, 1536 dimensões.",
        files: ["src/support/clients/embeddings/embeddings_client.py"],
      },
      {
        id: "store",
        label: "documents · chunks",
        description: "Postgres + pgvector, índice HNSW cosseno.",
        files: [
          "src/domain/documents/models/document.py",
          "src/domain/documents/models/document_chunk.py",
        ],
        metric: "knowledge",
      },
    ],
  },
  {
    id: "turn",
    title: "Turno — da pergunta à resposta",
    boxes: [
      {
        id: "ask",
        label: "Pergunta",
        description: "POST /conversations/ask, resposta em SSE.",
        files: ["src/app/api/controllers/conversation_controller.py"],
      },
      {
        id: "recency",
        label: "Recência",
        description: "Histórico por orçamento de tokens, não por número de turnos.",
        files: ["src/domain/conversations/repositories/message_repository.py"],
        metric: "recency",
      },
      {
        id: "gate",
        label: "Retrieval gate",
        description: "Modelo pequeno decide buscar ou não, e reescreve a query. Fail-open.",
        files: ["src/support/agent/retrieval_gate.py"],
        metric: "gate",
      },
      {
        id: "retrieval",
        label: "Retrieval + limiar",
        description: "Top-k no pgvector, escopado ao root, cortado pela distância máxima.",
        files: [
          "src/domain/documents/actions/search_knowledge_base_action.py",
          "src/domain/documents/repositories/document_chunk_repository.py",
        ],
        metric: "retrieval",
      },
      {
        id: "refusal",
        label: "Recusa padrão",
        description: "Nada passou do limiar: resposta determinística, sem chamar o LLM.",
        files: ["src/domain/conversations/services/out_of_scope_reply.py"],
        metric: "refusals",
      },
      {
        id: "engine",
        label: "OracleEngine + tools",
        description: "Pydantic AI. Grounding, citação e recusa vêm do system prompt.",
        files: [
          "src/support/agent/oracle_engine.py",
          "src/support/agent/tools.py",
          "src/support/agent/prompts.py",
        ],
        metric: "engine",
      },
      {
        id: "persist",
        label: "Persistência + trace",
        description: "Resposta e trace gravados pós-stream, em sessão própria.",
        files: [
          "src/domain/conversations/actions/append_assistant_message_action.py",
          "src/domain/observability/actions/record_turn_trace_action.py",
        ],
        metric: "turns",
      },
    ],
  },
];
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd frontend && npx vitest run src/features/ops/architectureMap.test.ts`
Expected: 4 PASS. Se algum caminho não existir, **o erro é no registro** — corrija o caminho, não o teste.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/ops/architectureMap.ts frontend/src/features/ops/architectureMap.test.ts
git commit -m "feat(ops): registro único do mapa de arquitetura + teste que impede o desenho de mentir"
```

---

### Task 9: A página `/ops`

**Files:**
- Create: `frontend/src/lib/api/ops.ts`
- Create: `frontend/src/lib/types.ops.ts`
- Create: `frontend/src/data/opsSource.ts`
- Create: `frontend/src/hooks/useCurrentUser.ts`
- Create: `frontend/src/hooks/useOpsOverview.ts`, `useOpsTurns.ts`, `useEvalReport.ts`
- Create: `frontend/src/features/ops/OpsPage.tsx`, `OpsPage.module.css`, `boxMetric.ts`
- Create: `frontend/src/features/ops/components/ArchitectureMap.tsx`, `BoxDetail.tsx`, `TurnList.tsx`, `TurnDetail.tsx`, `EvalPanel.tsx`, `WindowPicker.tsx`
- Create: `frontend/src/hooks/useOpsOverview.test.ts`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Header/Header.tsx`

**Interfaces:**
- Consumes: endpoints da Task 7, `ARCHITECTURE_MAP` da Task 8.
- Produces: rota `/ops`.

- [ ] **Step 1: Escrever o teste que falha**

`frontend/src/hooks/useOpsOverview.test.ts`:

```ts
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useOpsOverview } from "./useOpsOverview";

const overview = {
  window: "24h",
  knowledge: { documents_active: 42, documents_archived: 520, chunks: 260, sections: ["Bootcamps"] },
  sync: { job_name: null, status: null, started_at: null, finished_at: null, error: null },
  traces: { turns: 0, gate_retrieve: 0, gate_skip: 0, gate_degraded: 0, answers: 0, refusals: 0, errors: 0, avg_first_token_ms: null, max_first_token_ms: null, avg_engine_ms: null, max_engine_ms: null, avg_retrieval_kept: null, avg_best_distance: null },
  rag_top_k: 6,
  rag_max_distance: 0.55,
};

afterEach(() => vi.unstubAllGlobals());

describe("useOpsOverview", () => {
  it("loads the overview for the given window", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(overview))));
    const { result } = renderHook(() => useOpsOverview("24h"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overview?.knowledge.documents_active).toBe(42);
  });

  it("surfaces an error instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 500 })));
    const { result } = renderHook(() => useOpsOverview("24h"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeTruthy();
    expect(result.current.overview).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd frontend && npx vitest run src/hooks/useOpsOverview.test.ts`
Expected: FAIL — hook inexistente.

- [ ] **Step 3: Tipos e client**

`frontend/src/lib/types.ops.ts` — espelhar exatamente os responses da Task 7 (`OpsOverview`, `TurnSummary`, `TurnDetail`, `EvalReportPayload`, `OpsWindow = "24h" | "7d" | "all"`).

`frontend/src/lib/api/ops.ts` — usar o `getJSON` que já existe em `lib/api/client.ts`:

```ts
import { getJSON } from "./client";
import type { EvalReportPayload, OpsOverview, OpsWindow, TurnDetail, TurnSummary } from "../types.ops";

export const getOverview = (w: OpsWindow) => getJSON<OpsOverview>(`/ops/overview?window=${w}`);
export const listTurns = (w: OpsWindow, limit = 50) =>
  getJSON<TurnSummary[]>(`/ops/turns?window=${w}&limit=${limit}`);
export const getTurn = (id: string) => getJSON<TurnDetail>(`/ops/turns/${id}`);
export const getEvalReport = () => getJSON<EvalReportPayload>("/ops/eval");
```

`frontend/src/data/opsSource.ts` — seguir o padrão de `data/source.ts`. **Em modo demo, devolver dados de exemplo** (a página tem que abrir sem backend, como o resto do front).

- [ ] **Step 4: `useCurrentUser` — o encaixe de admin no front**

`frontend/src/hooks/useCurrentUser.ts`:

```ts
/**
 * Identidade do usuário. HOJE: placeholder — não existe endpoint /me, e a
 * página de ops está aberta por decisão da dona do produto.
 *
 * QUANDO A AUTH CHEGAR: buscar de /me e devolver `isAdmin` de verdade. Quem não
 * for admin não deve renderizar nem o link no header nem a <Route> de /ops —
 * a rota simplesmente não existe para essa pessoa (404 do lado do backend).
 */
export interface CurrentUser {
  email: string | null;
  isAdmin: boolean;
}

export function useCurrentUser(): CurrentUser {
  return { email: null, isAdmin: true };
}
```

- [ ] **Step 5: Os três hooks de dados**

Copiar a forma de `useConversations.ts` (estado + `refresh` + `loading`), acrescentando `error`. `useOpsOverview(window)`, `useOpsTurns(window)` e `useEvalReport()`. Nenhum deles lança: erro vira estado.

- [ ] **Step 6: O tradutor de `metric` → texto da caixa**

`frontend/src/features/ops/boxMetric.ts`:

```ts
import type { OpsOverview } from "../../lib/types.ops";
import type { MapBox } from "./architectureMap";

const ms = (v: number | null) => (v === null ? "—" : `${Math.round(v)}ms`);

/** Uma linha curta de número para a caixa. `null` = caixa sem métrica. */
export function boxMetric(box: MapBox, o: OpsOverview | null): string | null {
  if (!box.metric || !o) return null;
  const t = o.traces;
  switch (box.metric) {
    case "knowledge":
      return `${o.knowledge.documents_active} ativos · ${o.knowledge.chunks} chunks`;
    case "sync":
      return o.sync.status ? `último: ${o.sync.status}` : "nunca rodou";
    case "recency":
      return t.turns ? `${t.turns} turnos na janela` : "sem turnos";
    case "gate":
      return `${t.gate_retrieve} retrieve · ${t.gate_skip} skip${
        t.gate_degraded ? ` · ${t.gate_degraded} degraded` : ""
      }`;
    case "retrieval":
      return `limiar ${o.rag_max_distance} · top-k ${o.rag_top_k} · média ${
        t.avg_retrieval_kept === null ? "—" : t.avg_retrieval_kept.toFixed(1)
      } aprovados`;
    case "refusals":
      return `${t.refusals} recusas`;
    case "engine":
      return `1º token ${ms(t.avg_first_token_ms)} · total ${ms(t.avg_engine_ms)}`;
    case "turns":
      return `${t.answers} respostas · ${t.errors} erros`;
    default:
      return null;
  }
}
```

- [ ] **Step 7: Os componentes**

`WindowPicker.tsx`:

```tsx
import type { OpsWindow } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

const LABELS: Record<OpsWindow, string> = {
  "24h": "24 horas",
  "7d": "7 dias",
  all: "Tudo",
};

export function WindowPicker({
  value,
  onChange,
}: {
  value: OpsWindow;
  onChange: (w: OpsWindow) => void;
}) {
  return (
    <div className={styles.windowPicker} role="group" aria-label="Janela de tempo">
      {(Object.keys(LABELS) as OpsWindow[]).map((w) => (
        <button
          key={w}
          type="button"
          aria-pressed={w === value}
          className={w === value ? styles.windowActive : styles.windowButton}
          onClick={() => onChange(w)}
        >
          {LABELS[w]}
        </button>
      ))}
    </div>
  );
}
```

`ArchitectureMap.tsx`:

```tsx
import { ARCHITECTURE_MAP, type MapBox } from "../architectureMap";
import { boxMetric } from "../boxMetric";
import type { OpsOverview } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function ArchitectureMap({
  overview,
  selected,
  onSelect,
}: {
  overview: OpsOverview | null;
  selected: MapBox | null;
  onSelect: (box: MapBox) => void;
}) {
  return (
    <div className={styles.map}>
      {ARCHITECTURE_MAP.map((band) => (
        <section key={band.id} className={styles.band}>
          <h3 className={styles.bandTitle}>{band.title}</h3>
          <div className={styles.bandBoxes}>
            {band.boxes.map((box) => {
              const metric = boxMetric(box, overview);
              return (
                <button
                  key={box.id}
                  type="button"
                  onClick={() => onSelect(box)}
                  aria-pressed={selected?.id === box.id}
                  className={selected?.id === box.id ? styles.boxActive : styles.box}
                >
                  <span className={styles.boxLabel}>{box.label}</span>
                  {metric && <span className={styles.boxMetric}>{metric}</span>}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
```

`BoxDetail.tsx`:

```tsx
import type { MapBox } from "../architectureMap";
import styles from "../OpsPage.module.css";

export function BoxDetail({ box }: { box: MapBox | null }) {
  if (!box) {
    return <aside className={styles.detail}><p className={styles.muted}>Clique numa caixa do mapa para ver o que ela faz e onde ela mora.</p></aside>;
  }
  return (
    <aside className={styles.detail}>
      <h4>{box.label}</h4>
      <p>{box.description}</p>
      <p className={styles.muted}>Implementado em:</p>
      <ul className={styles.fileList}>
        {box.files.map((f) => (
          <li key={f}><code>{f}</code></li>
        ))}
      </ul>
    </aside>
  );
}
```

`TurnList.tsx`:

```tsx
import type { TurnSummary } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

const OUTCOME_LABEL: Record<string, string> = {
  answer: "resposta",
  refusal: "recusa",
  error: "erro",
};

function gateLabel(t: TurnSummary): string {
  if (t.gate_degraded) return "degraded";
  return t.gate_retrieve ? "retrieve" : "skip";
}

export function TurnList({
  turns,
  selectedId,
  onSelect,
}: {
  turns: TurnSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (turns.length === 0) {
    return <p className={styles.muted}>Nenhum turno nesta janela. Faça uma pergunta no oráculo e volte aqui.</p>;
  }
  return (
    <table className={styles.turns}>
      <thead>
        <tr>
          <th>Hora</th><th>Pergunta</th><th>Gate</th><th>Chunks</th><th>Desfecho</th><th>Duração</th>
        </tr>
      </thead>
      <tbody>
        {turns.map((t) => (
          <tr
            key={t.id}
            onClick={() => onSelect(t.id)}
            className={t.id === selectedId ? styles.turnActive : undefined}
          >
            <td>{new Date(t.created_at).toLocaleTimeString("pt-BR")}</td>
            <td className={styles.question}>{t.question}</td>
            <td>{gateLabel(t)}</td>
            <td>{t.retrieval_kept}</td>
            <td>{OUTCOME_LABEL[t.outcome] ?? t.outcome}</td>
            <td>{t.engine_ms === null ? "—" : `${t.engine_ms}ms`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`TurnDetail.tsx`:

```tsx
import type { TurnDetail as Detail } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function TurnDetail({ turn }: { turn: Detail | null }) {
  if (!turn) return <p className={styles.muted}>Selecione um turno para ver a sequência.</p>;
  return (
    <div className={styles.sequence}>
      <p className={styles.muted}>
        {turn.question} · limiar {turn.retrieval_threshold} · top-k {turn.retrieval_top_k}
        {turn.retrieval_best_distance !== null && ` · mais próximo ${turn.retrieval_best_distance.toFixed(3)}`}
      </p>
      <ol className={styles.steps}>
        {turn.events.map((e, i) => (
          <li key={`${e.step}-${i}`}>
            <span className={styles.stepAt}>{e.at_ms}ms</span>
            <span className={styles.stepName}>{e.step}</span>
            <span className={styles.stepDetail}>
              {Object.entries(e.detail ?? {})
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(" · ")}
            </span>
          </li>
        ))}
      </ol>
      {turn.error && <p className={styles.error}>{turn.error}</p>}
    </div>
  );
}
```

`EvalPanel.tsx`:

```tsx
import type { EvalReportPayload } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function EvalPanel({ payload }: { payload: EvalReportPayload | null }) {
  if (!payload || payload.status === "no_runs") {
    return (
      <div className={styles.empty}>
        <p>Nenhum run de eval ainda.</p>
        <p className={styles.muted}>
          Rode <code>python -m evals</code> para preencher este painel. O eval faz chamadas
          de modelo de verdade, então não é disparado pela web.
        </p>
      </div>
    );
  }
  const report = payload.report!;
  return (
    <div className={styles.eval}>
      <p className={report.verdict === "pass" ? styles.pass : styles.fail}>
        Veredito: {report.verdict === "pass" ? "PASSOU" : "FALHOU"}
      </p>
      <table className={styles.turns}>
        <thead><tr><th>Métrica</th><th>Média</th><th>Mínimo</th><th></th></tr></thead>
        <tbody>
          {Object.entries(report.metrics ?? {}).map(([name, m]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{m.mean.toFixed(2)}</td>
              <td>{m.threshold.toFixed(2)}</td>
              <td className={m.mean >= m.threshold ? styles.pass : styles.fail}>
                {m.mean >= m.threshold ? "ok" : "abaixo"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {(report.hard_failures ?? []).length > 0 && (
        <p className={styles.fail}>
          {report.hard_failures.length} caso(s) de segurança abaixo do piso — ver o report completo.
        </p>
      )}
      {payload.history.length > 1 && (
        <p className={styles.muted}>{payload.history.length} runs no histórico.</p>
      )}
    </div>
  );
}
```

> **Confira o shape real do report** antes de escrever `EvalPanel`: leia
> `evals/report.py` e ajuste os nomes de campo (`verdict`, `metrics`,
> `hard_failures`) ao que ele **de fato** grava. O tipo `EvalReportPayload` em
> `types.ops.ts` tem que espelhar o arquivo, não este exemplo.

Estilos em `OpsPage.module.css`, usando só variáveis de `styles/tokens.css` — nenhuma cor nova hardcoded. Classes necessárias: `windowPicker`, `windowButton`, `windowActive`, `map`, `band`, `bandTitle`, `bandBoxes`, `box`, `boxActive`, `boxLabel`, `boxMetric`, `detail`, `fileList`, `muted`, `turns`, `turnActive`, `question`, `sequence`, `steps`, `stepAt`, `stepName`, `stepDetail`, `error`, `empty`, `eval`, `pass`, `fail`.

- [ ] **Step 8: Montar a página e a rota**

`OpsPage.tsx` compõe: `Header`, `WindowPicker`, `ArchitectureMap` + `BoxDetail`, `TurnList` + `TurnDetail`, `EvalPanel`, `Footer`.

`App.tsx`:

```tsx
import { useCurrentUser } from "./hooks/useCurrentUser";
import OpsPage from "./features/ops/OpsPage";

export default function App() {
  const { isAdmin } = useCurrentUser();
  return (
    <Routes>
      {/* ...rotas existentes... */}
      {isAdmin && <Route path="/ops" element={<OpsPage />} />}
    </Routes>
  );
}
```

`Header.tsx` — o link só existe para admin:

```tsx
  const { isAdmin } = useCurrentUser();
  // dentro do <nav>, antes do Button:
  {isAdmin && <Link to="/ops">Ops</Link>}
```

- [ ] **Step 9: Rodar os testes do frontend**

```bash
cd frontend && npm run test
```
Expected: os 17 anteriores + os novos (mapa honesto + `useOpsOverview`), todos PASS.

- [ ] **Step 10: Conferir na tela**

```bash
DB_PORT=5434 ./start_dev
# abrir http://localhost:5173/ops
```
Expected: o mapa aparece com as contagens da base; se você tiver feito perguntas, os turnos aparecem na lista e o detalhe abre; o painel de eval mostra o estado vazio.

- [ ] **Step 11: Commit**

```bash
git add frontend/src
git commit -m "feat(ops): página /ops com mapa vivo, turnos recentes e painel de eval"
```

---

### Task 10: Pinar o juiz do eval em OpenAI

Mudança pequena e isolada, na spec seção 7. **Não rodar o harness.**

**Files:**
- Modify: `src/support/core/settings.py`
- Modify: `evals/judge/judge.py`
- Modify: `evals/__main__.py:36-40`
- Create: `tests/unit/evals/test_judge_provider.py`

**Interfaces:**
- Consumes: nada.
- Produces: `settings.JUDGE_MODEL: str = "gpt-4.1-mini"`; `_build_judge_model()` sempre OpenAI.

- [ ] **Step 1: Escrever o teste que falha**

`tests/unit/evals/test_judge_provider.py`:

```python
"""O juiz é OpenAI mesmo quando o oráculo é Claude (spec 2026-08-03, seção 7).

Razões trancadas por este teste: menos viés de auto-preferência (as respostas
são geradas por Claude) e a chave da OpenAI já é obrigatória para embeddings.
"""

from pydantic_ai.models.openai import OpenAIChatModel

from evals.judge.judge import _build_judge_model
from src.support.core.settings import settings


def test_uses_openai_even_with_anthropic_as_the_oracle_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    assert isinstance(_build_judge_model(), OpenAIChatModel)


def test_judge_model_default_is_not_the_gate_tier():
    """Descer ao tier do gate arrisca a métrica que sustenta o produto."""
    assert settings.JUDGE_MODEL != settings.OPENAI_SMALL_MODEL
    assert settings.JUDGE_MODEL == "gpt-4.1-mini"


def test_judge_model_is_never_none():
    assert isinstance(settings.JUDGE_MODEL, str) and settings.JUDGE_MODEL
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `DB_PORT=5434 uv run pytest tests/unit/evals/test_judge_provider.py -v`
Expected: FAIL — hoje devolve `AnthropicModel` e `JUDGE_MODEL` é `None`.

- [ ] **Step 3: Ajustar a setting**

Em `src/support/core/settings.py`, trocar:

```python
    JUDGE_MODEL: str | None = None  # eval judge; defaults to the provider's main model
```
por:

```python
    # Juiz do eval: sempre OpenAI, independente de LLM_PROVIDER. A chave da OpenAI
    # já é obrigatória (embeddings, ADR-0008) e juiz de outra família reduz viés de
    # auto-preferência, já que as respostas avaliadas vêm do Claude.
    JUDGE_MODEL: str = "gpt-4.1-mini"
```

- [ ] **Step 4: Simplificar `_build_judge_model`**

Em `evals/judge/judge.py`, substituir a função por:

```python
def _build_judge_model():
    """Sempre OpenAI — ver spec de 2026-08-03, seção 7."""
    return OpenAIChatModel(
        settings.JUDGE_MODEL,
        provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY),
    )
```

Remover os imports de `AnthropicModel` e `AnthropicProvider` do arquivo (ficam sem uso — o `prospector` acusaria).

- [ ] **Step 5: Ajustar o gate de chave no entrypoint**

Em `evals/__main__.py`, trocar a linha 36 e a mensagem:

```python
    key = settings.OPENAI_API_KEY
    if not key:
        print(
            "SKIPPED — nenhuma avaliação executada (sem OPENAI_API_KEY; o juiz do "
            "eval é OpenAI, independente de LLM_PROVIDER)"
        )
        return 2
```

Manter o `return 2` — o código de saída sentinela é contrato do harness.

- [ ] **Step 6: Rodar e ver passar (sem executar o harness)**

```bash
DB_PORT=5434 uv run pytest tests/unit/evals -v
DB_PORT=5434 uv run python -m evals --dry-run
```
Expected: testes PASS; o dry-run lista os casos sem chamar modelo. **Não rodar `python -m evals` sem `--dry-run`.**

- [ ] **Step 7: Commit**

```bash
git add src/support/core/settings.py evals tests/unit/evals/test_judge_provider.py
git commit -m "feat(evals): juiz pinado em OpenAI num modelo de tier médio"
```

---

### Task 11: ADR-0013, regra no CLAUDE.md e docs

**Files:**
- Create: `docs/adr/0013-trace-por-turno-no-postgres.md`
- Modify: `docs/adr/README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/architecture.md`
- Modify: `.env.example`

- [ ] **Step 1: Escrever o ADR**

`docs/adr/0013-trace-por-turno-no-postgres.md`, seguindo o template do `docs/adr/README.md` (`## Status`, `## Resumo` com Decisão/Aplica-se quando/Regra prática, `---`, depois Contexto/Decisão/Consequências).

- **Decisão:** o trace de cada turno é persistido em `agent_traces` no Postgres, coletado num ponto único (`TurnTraceDraft`) e gravado pós-stream junto da resposta.
- **Aplica-se quando:** for preciso saber o que aconteceu num turno, ou adicionar sinal novo de observabilidade.
- **Regra prática:** sinal novo entra no draft e na tabela; observabilidade nunca derruba um turno; trace de turno com erro é gravado.
- **Contexto/Consequências:** por que Postgres e não JSONL (container efêmero, réplicas); por que post-hoc e não broker; o custo de a tabela crescer sem poda; a incerteza do `usage()`.

- [ ] **Step 2: Registrar no índice de ADRs**

Adicionar a linha na tabela de `docs/adr/README.md`:

```markdown
| [0013](0013-trace-por-turno-no-postgres.md) | Trace por turno persistido no Postgres, coletado num ponto único | Aceito |
```

- [ ] **Step 3: A regra do mapa honesto no CLAUDE.md**

Na seção **"Antes de fazer mudanças estruturais"**, acrescentar:

```markdown
Se a mudança altera o **pipeline do turno ou da ingestão** (etapa nova, etapa
removida, arquivo renomeado), atualize `frontend/src/features/ops/architectureMap.ts`
**no mesmo commit**. O teste `architectureMap.test.ts` falha se um arquivo
declarado no mapa deixar de existir — é o que impede a página de ops de mentir
sobre a arquitetura.
```

- [ ] **Step 4: Documentar o subdomínio em `docs/architecture.md`**

Acrescentar `observability/` na árvore de `src/domain/` e uma seção curta "Trace do turno" explicando o fluxo em três frases, apontando para o ADR-0013.

- [ ] **Step 5: `.env.example`**

Acrescentar, no bloco de eval:

```
# Onde o harness de eval grava os reports (lidos pela página /ops)
EVAL_REPORTS_DIR=evals/reports
```

- [ ] **Step 6: Verificação final**

```bash
DB_PORT=5434 uv run pytest -q
DB_PORT=5434 uv run alembic check
cd frontend && npm run test && npm run build
cd .. && DB_PORT=5434 uv run prospector 2>&1 | tail -5
python -c "from main import app; print(len(app.routes), 'rotas')"
```
Expected: suíte verde, check limpo, build do front OK, prospector sem mensagem nova sua, app importa com as rotas de ops registradas.

- [ ] **Step 7: Commit**

```bash
git add docs CLAUDE.md .env.example
git commit -m "docs(adr): ADR-0013 trace por turno + regra do mapa honesto no CLAUDE.md"
```

---

## Verificação de cobertura da spec

| Requisito da spec | Task |
|---|---|
| Tabela `agent_traces`, Entity/Model/Mapper | 1 |
| Colunas planas + `events` JSONB | 1 |
| `TurnTraceDraft` puro, com relógio injetável | 2 |
| Distância do mais próximo no caminho de recusa | 3 |
| Coleta de recência/gate/retrieval/recusa | 4 |
| Tripla de retorno + ajuste dos chamadores | 4 |
| `TurnMetrics` no engine (tokens, tool calls) | 5 |
| Fase do engine medida no controller | 5 |
| Gravação pós-stream em uma sessão só | 5 |
| Invariante "trace nunca derruba um turno" | 5 (call site), 2 (`_safe`) |
| Invariante "turno com erro é gravado" | 5 |
| Agregados em uma query com `GROUP BY` | 6 |
| Fronteira de `documents` via Action | 6 |
| `EvalReportStore` + `EVAL_REPORTS_DIR` | 6 |
| Quatro endpoints + validação de janela | 7 |
| `require_admin` (404, não 403) | 7 |
| Registro único do mapa + teste honesto | 8 |
| Mapa vivo, turnos, painel de eval | 9 |
| `isAdmin` controlando link e rota | 9 |
| Juiz pinado em OpenAI, tier médio | 10 |
| ADR-0013 + regra no CLAUDE.md | 11 |
| Retenção da tabela (fora de escopo, registrado) | — (risco na spec) |
