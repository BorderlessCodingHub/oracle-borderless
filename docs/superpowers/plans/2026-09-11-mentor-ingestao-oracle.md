# Mentor de aula — Oracle — Ingestão — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o áudio das aulas do programa Base em chunks com timestamp e embedding, por um comando de console que pode ser re-executado sem medo.

**Architecture:** Bounded context novo `src/domain/lessons/`, seguindo o padrão do repo (Entity ≠ Model, uma Action por caso de uso, sem facade). Reusa `EmbeddingsClient` e o pgvector já em produção; **não** reusa `ChunkingService`, porque transcrição não tem heading markdown e o fallback de janela de caractere perderia os timestamps. O comando `mentor:ingest` é irmão de `knowledge:ingest` e herda dele o formato de sessão, commit e rollback.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 async, Alembic, pgvector, Pydantic v2, `openai` (já dependência, usado pelo `EmbeddingsClient`), `httpx`, `ffmpeg` (binário externo), pytest, UV.

**Spec:** `docs/superpowers/specs/2026-09-11-mentor-de-aula-design.md` (seções 4 e 7)

## Global Constraints

- Branch de trabalho: `feat/speech-to-text`.
- Gerenciador de pacotes: **UV**. Rodar testes com `uv run pytest`, comandos com `uv run python cli.py <comando>`.
- Migrations em `database/migrations/versions/`, nomeadas `00NN_<slug>.py`, com `revision`/`down_revision` em string explícita. A última hoje é `0011_navigation_persistence` — a nova encadeia nela.
- Índice ANN criado por SQL cru na migration **e** declarado no `__table_args__` do model; sem as duas metades o `alembic check` acusa índice a remover (o `DocumentChunkModel` documenta o porquê).
- PK sempre UUID v7 pelo mixin `HasUUID`. Timestamps pelo `HasTimestamps`.
- Repositório pega a sessão de `CurrentAsyncSessionContext.get()` no `__init__`, como `DocumentRepository`.
- Valores exatos de configuração desta fase: `MENTOR_CHUNK_SIZE=800`, `MENTOR_MAX_ATTEMPTS=3`, `MENTOR_AUDIO_SEGMENT_SECONDS=600`, `MENTOR_TRANSCRIBE_MODEL="whisper-1"`, `MENTOR_TRANSCRIBE_LANGUAGE="pt"`.
- O segredo `BORDERLESS_INTERNAL_SECRET` deste repo é o mesmo valor que a `borderless-api` chama de `MENTOR_INGEST_SECRET`.
- Commits em português, seguindo o estilo do repo (`feat(mentor): ...`). Terminar com:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

| Arquivo | Responsabilidade |
| --- | --- |
| `database/migrations/versions/0012_mentor_lessons.py` | **Criar.** Tabelas `lessons` e `lesson_chunks` + índice HNSW |
| `src/domain/lessons/entities/lesson.py` | **Criar.** Dataclass de domínio da aula |
| `src/domain/lessons/entities/lesson_chunk.py` | **Criar.** Dataclass do trecho, com `start_seconds`/`end_seconds` |
| `src/domain/lessons/entities/transcript_segment.py` | **Criar.** Dataclass do segmento bruto do speech-to-text |
| `src/domain/lessons/models/lesson.py` | **Criar.** SQLAlchemy |
| `src/domain/lessons/models/lesson_chunk.py` | **Criar.** SQLAlchemy + `__table_args__` do HNSW |
| `src/domain/lessons/mappers/lesson_mapper.py` | **Criar.** Entity ⇄ Model |
| `src/domain/lessons/mappers/lesson_chunk_mapper.py` | **Criar.** Entity ⇄ Model |
| `src/domain/lessons/enums/__init__.py` | **Criar.** `TranscriptStatus` |
| `src/domain/lessons/services/transcript_chunking_service.py` | **Criar.** Puro: segmentos → chunks com timestamp |
| `src/domain/lessons/repositories/lesson_repository.py` | **Criar.** Upsert por `platform_video_id`, claim, listagem por status |
| `src/domain/lessons/repositories/lesson_chunk_repository.py` | **Criar.** `replace_for_lesson` |
| `src/support/clients/borderless/borderless_lessons_client.py` | **Criar.** HTTP para as duas rotas `/api/internal` |
| `src/support/clients/transcription/transcription_client.py` | **Criar.** Áudio → segmentos com timestamp |
| `src/support/clients/transcription/audio_toolkit.py` | **Criar.** Wrapper de `ffmpeg`/`ffprobe`: extrair e fatiar |
| `src/domain/lessons/actions/ingest_lesson_action.py` | **Criar.** Máquina de estados de uma aula |
| `src/domain/lessons/actions/sync_program_lessons_action.py` | **Criar.** Reconcilia a lista da API com a tabela |
| `src/app/console/commands/mentor_ingest_command.py` | **Criar.** `mentor:ingest` |
| `src/support/core/settings.py` | **Modificar.** Bloco `# --- Mentor ---` |

---

### Task 1: Tabelas, entidades e mappers

**Files:**
- Create: `src/domain/lessons/__init__.py`, `entities/lesson.py`, `entities/lesson_chunk.py`, `entities/transcript_segment.py`, `entities/__init__.py`, `enums/__init__.py`, `models/lesson.py`, `models/lesson_chunk.py`, `models/__init__.py`, `mappers/lesson_mapper.py`, `mappers/lesson_chunk_mapper.py`, `mappers/__init__.py`
- Create: `database/migrations/versions/0012_mentor_lessons.py`
- Modify: `src/support/core/settings.py`
- Test: `tests/unit/domain/lessons/test_mappers.py`, `tests/integration/test_migration_mentor_lessons.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `TranscriptStatus` — `PENDING`, `TRANSCRIBING`, `READY`, `FAILED` (valores string minúsculos)
  - `Lesson(uuid, platform_video_id, program_slug, module_slug, video_slug, title, duration_seconds, provider, provider_ref, transcript_text, transcript_status, content_hash, transcribed_at, attempts, failure_reason)`
  - `LessonChunk(uuid, lesson_id, ordinal, content, start_seconds, end_seconds, embedding)`
  - `TranscriptSegment(text, start, end)`
  - `LessonMapper.to_entity/to_model_attrs`, `LessonChunkMapper.to_entity/to_model_attrs`

- [ ] **Step 1: Acrescentar a configuração**

Em `src/support/core/settings.py`, depois do bloco de RAG, acrescente:

```python
    # --- Mentor de aula (spec 2026-09-11) ---
    MENTOR_ENABLED: bool = False
    # Chunk menor que o do Notion: fala é mais diluída que texto escrito, e
    # chunk grande demais dilui o embedding e piora a citação temporal.
    MENTOR_CHUNK_SIZE: int = 800
    MENTOR_TOP_K: int = 6
    MENTOR_MAX_ATTEMPTS: int = 3
    # A API de transcrição limita o arquivo a 25 MB; uma aula de 1h passa disso.
    MENTOR_AUDIO_SEGMENT_SECONDS: int = 600
    MENTOR_TRANSCRIBE_MODEL: str = "whisper-1"
    MENTOR_TRANSCRIBE_LANGUAGE: str = "pt"
    MENTOR_FFMPEG_BIN: str = "ffmpeg"
    MENTOR_FFPROBE_BIN: str = "ffprobe"
    # Rótulos de cobertura — NÃO bloqueiam nada, só classificam (spec §9.2).
    MENTOR_COVERAGE_NEAR: float = 0.35
    MENTOR_COVERAGE_FAR: float = 0.55
    # borderless-api: as rotas /api/internal. O segredo é o mesmo valor que lá
    # se chama MENTOR_INGEST_SECRET.
    BORDERLESS_INTERNAL_SECRET: str = ""
```

`BORDERLESS_AUTH_URL` já existe e é a base das chamadas.

- [ ] **Step 2: Escrever o teste dos mappers, que falha**

```python
# tests/unit/domain/lessons/test_mappers.py
from datetime import datetime, timezone
from uuid import uuid4

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.mappers.lesson_chunk_mapper import LessonChunkMapper
from src.domain.lessons.mappers.lesson_mapper import LessonMapper
from src.domain.lessons.models.lesson import LessonModel
from src.domain.lessons.models.lesson_chunk import LessonChunkModel


def _lesson(**overrides) -> Lesson:
    base = dict(
        uuid=uuid4(),
        platform_video_id="v1",
        program_slug="base",
        module_slug="modulo-1",
        video_slug="aula-1",
        title="Tokens e embeddings",
        duration_seconds=3600,
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
        transcript_text="oi",
        transcript_status=TranscriptStatus.READY,
        content_hash="abc",
        transcribed_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        attempts=1,
        failure_reason=None,
    )
    base.update(overrides)
    return Lesson(**base)


def test_lesson_round_trip_preserves_every_field():
    entity = _lesson()
    model = LessonModel(**LessonMapper.to_model_attrs(entity))
    assert LessonMapper.to_entity(model) == entity


def test_lesson_status_crosses_as_a_plain_string():
    attrs = LessonMapper.to_model_attrs(_lesson())
    assert attrs["transcript_status"] == "ready"
    assert isinstance(attrs["transcript_status"], str)


def test_chunk_round_trip_preserves_timestamps_and_vector():
    entity = LessonChunk(
        uuid=uuid4(),
        lesson_id=uuid4(),
        ordinal=3,
        content="sobre autorregressão",
        start_seconds=750.5,
        end_seconds=812.25,
        embedding=[0.1, 0.2, 0.3],
    )
    model = LessonChunkModel(**LessonChunkMapper.to_model_attrs(entity))
    assert LessonChunkMapper.to_entity(model) == entity


def test_chunk_without_embedding_maps_to_none():
    entity = LessonChunk(
        uuid=uuid4(), lesson_id=uuid4(), ordinal=0,
        content="x", start_seconds=0.0, end_seconds=1.0, embedding=None,
    )
    model = LessonChunkModel(**LessonChunkMapper.to_model_attrs(entity))
    assert LessonChunkMapper.to_entity(model).embedding is None
```

- [ ] **Step 3: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/domain/lessons/test_mappers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain.lessons'`

- [ ] **Step 4: Escrever enum, entidades, models e mappers**

```python
# src/domain/lessons/enums/__init__.py
from enum import StrEnum


class TranscriptStatus(StrEnum):
    """Ciclo de vida da transcrição de uma aula.

    `TRANSCRIBING` é o claim: existe para que duas execuções concorrentes do
    comando não transcrevam a mesma aula duas vezes.
    """

    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    READY = "ready"
    FAILED = "failed"
```

```python
# src/domain/lessons/entities/lesson.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.lessons.enums import TranscriptStatus


@dataclass
class Lesson:
    """Uma aula da plataforma e o estado da sua transcrição. Domínio puro."""

    uuid: UUID
    platform_video_id: str
    program_slug: str
    module_slug: str
    video_slug: str
    title: str
    duration_seconds: int | None = None
    provider: str = ""
    provider_ref: str = ""
    transcript_text: str | None = None
    transcript_status: TranscriptStatus = TranscriptStatus.PENDING
    content_hash: str | None = None
    transcribed_at: datetime | None = None
    attempts: int = 0
    failure_reason: str | None = None

    def is_ready(self) -> bool:
        return self.transcript_status == TranscriptStatus.READY

    def can_retry(self, max_attempts: int) -> bool:
        return self.attempts < max_attempts
```

```python
# src/domain/lessons/entities/lesson_chunk.py
from dataclasses import dataclass
from uuid import UUID


@dataclass
class LessonChunk:
    """Trecho de uma aula, com a janela de tempo de onde ele veio."""

    uuid: UUID
    lesson_id: UUID
    ordinal: int
    content: str
    start_seconds: float
    end_seconds: float
    embedding: list[float] | None = None
```

```python
# src/domain/lessons/entities/transcript_segment.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptSegment:
    """Um segmento cru do speech-to-text, antes de virar chunk."""

    text: str
    start: float
    end: float

    def shifted(self, offset: float) -> "TranscriptSegment":
        """Desloca no tempo — usado ao concatenar blocos de áudio fatiados."""
        return TranscriptSegment(text=self.text, start=self.start + offset, end=self.end + offset)
```

```python
# src/domain/lessons/models/lesson.py
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class LessonModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    __tablename__ = "lessons"

    platform_video_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    program_slug: Mapped[str] = mapped_column(String(255), index=True)
    module_slug: Mapped[str] = mapped_column(String(255))
    video_slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_ref: Mapped[str] = mapped_column(String(255))
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(String(20), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

```python
# src/domain/lessons/models/lesson_chunk.py
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel
from src.support.core.settings import settings


class LessonChunkModel(BaseModel, HasUUID, HasTimestamps):
    __tablename__ = "lesson_chunks"

    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.uuid", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=True
    )

    # Mesmo motivo do DocumentChunkModel: o índice nasce na migration por SQL
    # cru, e sem esta declaração o autogenerate do Alembic o veria como índice
    # a remover em todo `alembic check`.
    __table_args__ = (
        Index(
            "ix_lesson_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
```

```python
# src/domain/lessons/mappers/lesson_mapper.py
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.models.lesson import LessonModel


class LessonMapper:
    @staticmethod
    def to_entity(model: LessonModel) -> Lesson:
        return Lesson(
            uuid=model.uuid,
            platform_video_id=model.platform_video_id,
            program_slug=model.program_slug,
            module_slug=model.module_slug,
            video_slug=model.video_slug,
            title=model.title,
            duration_seconds=model.duration_seconds,
            provider=model.provider,
            provider_ref=model.provider_ref,
            transcript_text=model.transcript_text,
            transcript_status=TranscriptStatus(model.transcript_status),
            content_hash=model.content_hash,
            transcribed_at=model.transcribed_at,
            attempts=model.attempts,
            failure_reason=model.failure_reason,
        )

    @staticmethod
    def to_model_attrs(entity: Lesson) -> dict:
        return {
            "uuid": entity.uuid,
            "platform_video_id": entity.platform_video_id,
            "program_slug": entity.program_slug,
            "module_slug": entity.module_slug,
            "video_slug": entity.video_slug,
            "title": entity.title,
            "duration_seconds": entity.duration_seconds,
            "provider": entity.provider,
            "provider_ref": entity.provider_ref,
            "transcript_text": entity.transcript_text,
            "transcript_status": str(entity.transcript_status),
            "content_hash": entity.content_hash,
            "transcribed_at": entity.transcribed_at,
            "attempts": entity.attempts,
            "failure_reason": entity.failure_reason,
        }
```

```python
# src/domain/lessons/mappers/lesson_chunk_mapper.py
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.models.lesson_chunk import LessonChunkModel


class LessonChunkMapper:
    @staticmethod
    def to_entity(model: LessonChunkModel) -> LessonChunk:
        return LessonChunk(
            uuid=model.uuid,
            lesson_id=model.lesson_id,
            ordinal=model.ordinal,
            content=model.content,
            start_seconds=model.start_seconds,
            end_seconds=model.end_seconds,
            embedding=list(model.embedding) if model.embedding is not None else None,
        )

    @staticmethod
    def to_model_attrs(entity: LessonChunk) -> dict:
        return {
            "uuid": entity.uuid,
            "lesson_id": entity.lesson_id,
            "ordinal": entity.ordinal,
            "content": entity.content,
            "start_seconds": entity.start_seconds,
            "end_seconds": entity.end_seconds,
            "embedding": entity.embedding,
        }
```

Crie os `__init__.py` de `entities/`, `models/` e `mappers/` reexportando as
classes, no mesmo formato dos `__init__.py` de `src/domain/documents/`.

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/domain/lessons/test_mappers.py -v`
Expected: PASS — 4 testes

- [ ] **Step 6: Escrever a migration**

```python
# database/migrations/versions/0012_mentor_lessons.py
"""lessons e lesson_chunks — base do mentor de aula (spec 2026-09-11 §4).

Revision ID: 0012_mentor_lessons
Revises: 0011_navigation_persistence
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from src.support.core.settings import settings

revision = "0012_mentor_lessons"
down_revision = "0011_navigation_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lessons",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("platform_video_id", sa.String(64), nullable=False),
        sa.Column("program_slug", sa.String(255), nullable=False),
        sa.Column("module_slug", sa.String(255), nullable=False),
        sa.Column("video_slug", sa.String(255), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False),
        sa.Column("transcript_text", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lessons_platform_video_id", "lessons", ["platform_video_id"], unique=True)
    op.create_index("ix_lessons_program_slug", "lessons", ["program_slug"])
    op.create_index("ix_lessons_transcript_status", "lessons", ["transcript_status"])

    op.create_table(
        "lesson_chunks",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.uuid", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(settings.EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lesson_chunks_lesson_id", "lesson_chunks", ["lesson_id"])
    # HNSW por SQL cru: o Alembic não emite `USING hnsw` com opclass.
    op.execute(
        "CREATE INDEX ix_lesson_chunks_embedding_hnsw "
        "ON lesson_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lesson_chunks_embedding_hnsw")
    op.drop_table("lesson_chunks")
    op.drop_table("lessons")
```

Abra `database/migrations/versions/0001_*.py` e confirme como a extensão
`vector` e o índice HNSW de `document_chunks` foram escritos lá; se o estilo
divergir do acima (por exemplo `sa.dialects.postgresql.UUID` em vez de
`sa.Uuid`), **siga o do repo**, não o deste plano.

- [ ] **Step 7: Aplicar a migration e conferir**

Run: `uv run alembic upgrade head`
Expected: sem erro

Run: `uv run alembic check`
Expected: "No new upgrade operations detected" — se acusar índice a remover, a
declaração do `__table_args__` no model não bateu com a do SQL cru.

- [ ] **Step 8: Commit**

```bash
git add src/domain/lessons database/migrations/versions/0012_mentor_lessons.py src/support/core/settings.py tests/unit/domain/lessons
git commit -m "feat(mentor): tabelas, entidades e mappers das aulas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: TranscriptChunkingService

**Files:**
- Create: `src/domain/lessons/services/transcript_chunking_service.py`, `src/domain/lessons/services/__init__.py`
- Test: `tests/unit/domain/lessons/test_transcript_chunking_service.py`

**Interfaces:**
- Consumes: `TranscriptSegment` (Task 1).
- Produces: `TranscriptChunkingService(size: int | None = None)` com
  `split(segments: list[TranscriptSegment]) -> list[tuple[str, float, float]]`,
  devolvendo `(texto, start_seconds, end_seconds)` por chunk, na ordem.

- [ ] **Step 1: Escrever os testes, que falham**

```python
# tests/unit/domain/lessons/test_transcript_chunking_service.py
import pytest

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.services.transcript_chunking_service import TranscriptChunkingService


def seg(text: str, start: float, end: float) -> TranscriptSegment:
    return TranscriptSegment(text=text, start=start, end=end)


def test_empty_input_yields_no_chunks():
    assert TranscriptChunkingService(size=100).split([]) == []


def test_segments_under_the_limit_become_a_single_chunk():
    chunks = TranscriptChunkingService(size=100).split(
        [seg("olá pessoal", 0.0, 2.0), seg("hoje é sobre tokens", 2.0, 5.0)]
    )
    assert chunks == [("olá pessoal hoje é sobre tokens", 0.0, 5.0)]


def test_packing_fills_exactly_to_the_limit_then_breaks():
    # 15 + 1 (espaço) + 4 = 20 == size: cabe (limite inclusivo); o próximo estoura.
    service = TranscriptChunkingService(size=20)
    chunks = service.split(
        [seg("a" * 15, 0.0, 1.0), seg("b" * 4, 1.0, 2.0), seg("c" * 10, 2.0, 3.0)]
    )
    assert [c[0] for c in chunks] == ["a" * 15 + " " + "b" * 4, "c" * 10]
    assert chunks[0][1] == 0.0 and chunks[0][2] == 2.0
    assert chunks[1][1] == 2.0 and chunks[1][2] == 3.0


def test_one_char_over_the_limit_breaks_the_chunk():
    # 15 + 1 + 5 = 21 > 20: NÃO cabe. "Até size" é teto duro, sem tolerância.
    service = TranscriptChunkingService(size=20)
    chunks = service.split([seg("a" * 15, 0.0, 1.0), seg("b" * 5, 1.0, 2.0)])
    assert [c[0] for c in chunks] == ["a" * 15, "b" * 5]


def test_a_segment_longer_than_the_limit_becomes_its_own_chunk_unsplit():
    # Cortar dentro de um segmento perderia a única âncora temporal que ele tem.
    long_text = "x" * 50
    chunks = TranscriptChunkingService(size=20).split([seg(long_text, 10.0, 40.0)])
    assert chunks == [(long_text, 10.0, 40.0)]


def test_blank_segments_are_dropped_without_breaking_the_window():
    chunks = TranscriptChunkingService(size=100).split(
        [seg("  ", 0.0, 1.0), seg("conteúdo", 1.0, 2.0), seg("", 2.0, 3.0)]
    )
    assert chunks == [("conteúdo", 1.0, 2.0)]


def test_chunks_come_back_in_chronological_order():
    service = TranscriptChunkingService(size=10)
    chunks = service.split([seg("aaaaaaa", 0.0, 1.0), seg("bbbbbbb", 1.0, 2.0), seg("ccccccc", 2.0, 3.0)])
    starts = [c[1] for c in chunks]
    assert starts == sorted(starts)


def test_size_must_be_positive():
    with pytest.raises(ValueError):
        TranscriptChunkingService(size=0)
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/domain/lessons/test_transcript_chunking_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```python
# src/domain/lessons/services/transcript_chunking_service.py
"""TranscriptChunkingService — segmentos de fala em chunks com janela de tempo.

Puro, sem I/O. Por que não reusar o `ChunkingService` de `documents`: ele corta
por heading markdown e, na ausência deles, cai em janela de caractere — o que
descarta a informação que aqui é a mais valiosa, o instante em que cada frase
foi dita (spec §4).

Estratégia: empacotar segmentos consecutivos enquanto couberem em `size`; o
`start` do chunk é o do primeiro segmento e o `end` é o do último. Segmento
maior que `size` vira um chunk sozinho, sem corte: quebrá-lo no meio perderia a
única âncora temporal que ele tem, e um segmento de fala já é curto por
natureza.
"""

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.support.core.settings import settings

Chunk = tuple[str, float, float]


class TranscriptChunkingService:
    def __init__(self, size: int | None = None) -> None:
        self.size = size if size is not None else settings.MENTOR_CHUNK_SIZE
        if self.size <= 0:
            raise ValueError("size deve ser positivo")

    def split(self, segments: list[TranscriptSegment]) -> list[Chunk]:
        usable = [s for s in segments if s.text.strip()]
        if not usable:
            return []

        chunks: list[Chunk] = []
        texts: list[str] = []
        start = 0.0
        end = 0.0

        for segment in usable:
            text = segment.text.strip()
            if not texts:
                texts, start, end = [text], segment.start, segment.end
                continue
            candidate = len(" ".join(texts)) + 1 + len(text)
            if candidate > self.size:
                chunks.append((" ".join(texts), start, end))
                texts, start, end = [text], segment.start, segment.end
            else:
                texts.append(text)
                end = segment.end

        chunks.append((" ".join(texts), start, end))
        return chunks
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/domain/lessons/test_transcript_chunking_service.py -v`
Expected: PASS — 8 testes

- [ ] **Step 5: Commit**

```bash
git add src/domain/lessons/services tests/unit/domain/lessons/test_transcript_chunking_service.py
git commit -m "feat(mentor): chunking de transcrição preservando timestamps

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Repositórios

**Files:**
- Create: `src/domain/lessons/repositories/lesson_repository.py`, `lesson_chunk_repository.py`, `__init__.py`
- Test: `tests/integration/domain/lessons/test_lesson_repository.py`

**Interfaces:**
- Consumes: `Lesson`, `LessonChunk`, mappers, `TranscriptStatus` (Task 1).
- Produces:
  - `LessonRepository.upsert_from_catalog(lesson: Lesson) -> Lesson` — cria ou atualiza os campos de catálogo por `platform_video_id`, **sem tocar** em estado de transcrição
  - `LessonRepository.get_by_platform_video_id(video_id: str) -> Lesson | None`
  - `LessonRepository.list_pending(program_slug: str, max_attempts: int) -> list[Lesson]`
  - `LessonRepository.save(lesson: Lesson) -> Lesson`
  - `LessonChunkRepository.replace_for_lesson(lesson_id: UUID, chunks: list[LessonChunk]) -> None`
  - `LessonChunkRepository.count_for_lesson(lesson_id: UUID) -> int`

- [ ] **Step 1: Escrever o teste de integração, que falha**

Siga o formato de `tests/integration/domain/documents/test_chunk_repository_nearest.py`
para a fixture de sessão — abra o arquivo e reuse exatamente a mesma fixture.

```python
# tests/integration/domain/lessons/test_lesson_repository.py
from uuid import uuid4

import pytest

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository


def _catalog_lesson(video_id: str = "v1", title: str = "Tokens") -> Lesson:
    return Lesson(
        uuid=uuid4(),
        platform_video_id=video_id,
        program_slug="base",
        module_slug="modulo-1",
        video_slug="aula-1",
        title=title,
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
    )


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_without_losing_transcript_state(db_session):
    repo = LessonRepository()

    created = await repo.upsert_from_catalog(_catalog_lesson())
    created.transcript_status = TranscriptStatus.READY
    created.transcript_text = "conteúdo"
    created.content_hash = "hash-1"
    await repo.save(created)

    again = await repo.upsert_from_catalog(_catalog_lesson(title="Tokens (revisado)"))

    assert again.uuid == created.uuid
    assert again.title == "Tokens (revisado)"
    assert again.transcript_status == TranscriptStatus.READY
    assert again.content_hash == "hash-1"


@pytest.mark.asyncio
async def test_list_pending_returns_pending_and_failed_under_the_attempt_ceiling(db_session):
    repo = LessonRepository()

    pending = await repo.upsert_from_catalog(_catalog_lesson("v-pending"))

    failed = await repo.upsert_from_catalog(_catalog_lesson("v-failed"))
    failed.transcript_status = TranscriptStatus.FAILED
    failed.attempts = 1
    await repo.save(failed)

    exhausted = await repo.upsert_from_catalog(_catalog_lesson("v-exhausted"))
    exhausted.transcript_status = TranscriptStatus.FAILED
    exhausted.attempts = 3
    await repo.save(exhausted)

    ready = await repo.upsert_from_catalog(_catalog_lesson("v-ready"))
    ready.transcript_status = TranscriptStatus.READY
    await repo.save(ready)

    ids = {l.platform_video_id for l in await repo.list_pending("base", max_attempts=3)}
    assert ids == {"v-pending", "v-failed"}


@pytest.mark.asyncio
async def test_replace_for_lesson_is_idempotent(db_session):
    lesson = await LessonRepository().upsert_from_catalog(_catalog_lesson("v-chunks"))
    chunks_repo = LessonChunkRepository()

    def chunk(i: int) -> LessonChunk:
        return LessonChunk(
            uuid=uuid4(), lesson_id=lesson.uuid, ordinal=i, content=f"trecho {i}",
            start_seconds=float(i * 10), end_seconds=float(i * 10 + 9),
            embedding=[0.0] * 1536,
        )

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0), chunk(1)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 2

    await chunks_repo.replace_for_lesson(lesson.uuid, [chunk(0)])
    assert await chunks_repo.count_for_lesson(lesson.uuid) == 1
```

Se a fixture de sessão do repo tiver outro nome que não `db_session`, use o nome
real — confira em `tests/integration/conftest.py`.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/integration/domain/lessons/test_lesson_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar os repositórios**

```python
# src/domain/lessons/repositories/lesson_repository.py
from sqlalchemy import select

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.mappers.lesson_mapper import LessonMapper
from src.domain.lessons.models.lesson import LessonModel
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.exceptions import NotFoundError

# Campos que vêm do catálogo da plataforma. O estado de transcrição NÃO está
# aqui de propósito: re-sincronizar o catálogo não pode jogar fora o trabalho
# de transcrição já feito.
_CATALOG_FIELDS = (
    "program_slug",
    "module_slug",
    "video_slug",
    "title",
    "duration_seconds",
    "provider",
    "provider_ref",
)


class LessonRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def _model_by_video_id(self, video_id: str) -> LessonModel | None:
        result = await self.session.execute(
            select(LessonModel).where(LessonModel.platform_video_id == video_id)
        )
        return result.scalar_one_or_none()

    async def get_by_platform_video_id(self, video_id: str) -> Lesson | None:
        model = await self._model_by_video_id(video_id)
        return LessonMapper.to_entity(model) if model else None

    async def upsert_from_catalog(self, lesson: Lesson) -> Lesson:
        model = await self._model_by_video_id(lesson.platform_video_id)
        attrs = LessonMapper.to_model_attrs(lesson)
        if model is None:
            model = LessonModel(**attrs)
            self.session.add(model)
        else:
            for key in _CATALOG_FIELDS:
                setattr(model, key, attrs[key])
        await self.session.flush()
        await self.session.refresh(model)
        return LessonMapper.to_entity(model)

    async def save(self, lesson: Lesson) -> Lesson:
        model = await self._model_by_video_id(lesson.platform_video_id)
        if model is None:
            raise NotFoundError(f"aula {lesson.platform_video_id} não existe")
        for key, value in LessonMapper.to_model_attrs(lesson).items():
            if key != "uuid":
                setattr(model, key, value)
        await self.session.flush()
        await self.session.refresh(model)
        return LessonMapper.to_entity(model)

    async def list_pending(self, program_slug: str, max_attempts: int) -> list[Lesson]:
        """Aulas que o lote deve processar: nunca transcritas, ou que falharam e
        ainda têm tentativa. `transcribing` fica de fora — é claim de outra
        execução."""
        result = await self.session.execute(
            select(LessonModel)
            .where(
                LessonModel.program_slug == program_slug,
                LessonModel.transcript_status.in_(
                    [str(TranscriptStatus.PENDING), str(TranscriptStatus.FAILED)]
                ),
                LessonModel.attempts < max_attempts,
            )
            .order_by(LessonModel.created_at)
        )
        return [LessonMapper.to_entity(m) for m in result.scalars().all()]
```

```python
# src/domain/lessons/repositories/lesson_chunk_repository.py
from uuid import UUID

from sqlalchemy import delete, func, select

from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.mappers.lesson_chunk_mapper import LessonChunkMapper
from src.domain.lessons.models.lesson_chunk import LessonChunkModel
from src.support.core.context import CurrentAsyncSessionContext


class LessonChunkRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def replace_for_lesson(self, lesson_id: UUID, chunks: list[LessonChunk]) -> None:
        await self.session.execute(
            delete(LessonChunkModel).where(LessonChunkModel.lesson_id == lesson_id)
        )
        for chunk in chunks:
            self.session.add(LessonChunkModel(**LessonChunkMapper.to_model_attrs(chunk)))
        await self.session.flush()

    async def count_for_lesson(self, lesson_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LessonChunkModel)
            .where(LessonChunkModel.lesson_id == lesson_id)
        )
        return result.scalar_one()
```

A busca por similaridade **não** entra aqui: ela é do plano do mentor (fase 2),
não da ingestão.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/integration/domain/lessons/test_lesson_repository.py -v`
Expected: PASS — 3 testes

- [ ] **Step 5: Commit**

```bash
git add src/domain/lessons/repositories tests/integration/domain/lessons
git commit -m "feat(mentor): repositórios de aula e de chunk

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Cliente HTTP da borderless-api

**Files:**
- Create: `src/support/clients/borderless/borderless_lessons_client.py`
- Test: `tests/unit/support/clients/test_borderless_lessons_client.py`

**Interfaces:**
- Consumes: `settings.BORDERLESS_AUTH_URL`, `settings.BORDERLESS_INTERNAL_SECRET`.
- Produces:
  - `@dataclass(frozen=True) CatalogLesson(platform_video_id, program_slug, module_slug, video_slug, title, provider, provider_ref, duration_seconds)`
  - `@dataclass(frozen=True) LessonMedia(url, expires_at, content_type)`
  - `BorderlessLessonsClient.list_program_lessons(program_slug: str) -> list[CatalogLesson]`
  - `BorderlessLessonsClient.get_media(video_id: str) -> LessonMedia`
  - `LessonCatalogUnavailableError(DomainError)`

- [ ] **Step 1: Escrever o teste, que falha**

Use `respx` se o repo já o tiver (`grep -rn "respx" pyproject.toml`); se não
tiver, monte o teste com um `httpx.MockTransport`, que não exige dependência
nova. O teste abaixo usa `MockTransport`.

```python
# tests/unit/support/clients/test_borderless_lessons_client.py
import httpx
import pytest

from src.support.clients.borderless.borderless_lessons_client import (
    BorderlessLessonsClient,
    LessonCatalogUnavailableError,
)


def client_with(handler) -> BorderlessLessonsClient:
    return BorderlessLessonsClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_lists_lessons_and_maps_every_field():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-internal-secret"] != ""
        assert request.url.path == "/api/internal/programs/base/lessons"
        return httpx.Response(200, json={"data": {"lessons": [{
            "id": "v1", "programSlug": "base", "moduleSlug": "m1", "videoSlug": "a1",
            "title": "Tokens", "provider": "PANDA_VIDEO", "providerRef": "ref-1",
            "durationSeconds": None,
        }]}})

    lessons = await client_with(handler).list_program_lessons("base")

    assert len(lessons) == 1
    assert lessons[0].platform_video_id == "v1"
    assert lessons[0].provider_ref == "ref-1"
    assert lessons[0].duration_seconds is None


@pytest.mark.asyncio
async def test_the_secret_never_appears_in_the_url():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": {"lessons": []}})

    await client_with(handler).list_program_lessons("base")
    assert all("secret" not in url.lower() for url in seen)


@pytest.mark.asyncio
async def test_unknown_program_raises_unavailable_with_the_status():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "program not found"}})

    with pytest.raises(LessonCatalogUnavailableError) as exc:
        await client_with(handler).list_program_lessons("ghost")
    assert "404" in str(exc.value)


@pytest.mark.asyncio
async def test_media_maps_the_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/videos/v1/media"
        return httpx.Response(200, json={"data": {
            "url": "https://cdn.test/a.m3u8", "expiresAt": None, "contentType": "application/vnd.apple.mpegurl",
        }})

    media = await client_with(handler).get_media("v1")
    assert media.url == "https://cdn.test/a.m3u8"
    assert media.content_type == "application/vnd.apple.mpegurl"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/support/clients/test_borderless_lessons_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar o cliente**

```python
# src/support/clients/borderless/borderless_lessons_client.py
"""Cliente das rotas /api/internal da borderless-api — catálogo de aulas e URL
de mídia para a ingestão do mentor (spec §6). Autenticado por segredo
compartilhado em header, não por sessão de usuário: o consumidor é um lote
offline. O segredo viaja SÓ no header e nunca é logado."""

import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import DomainError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_HEADER = "X-Internal-Secret"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LessonCatalogUnavailableError(DomainError):
    """A borderless-api não respondeu o que a ingestão precisa."""


@dataclass(frozen=True)
class CatalogLesson:
    platform_video_id: str
    program_slug: str
    module_slug: str
    video_slug: str
    title: str
    provider: str
    provider_ref: str
    duration_seconds: int | None


@dataclass(frozen=True)
class LessonMedia:
    url: str
    expires_at: str | None
    content_type: str | None


class BorderlessLessonsClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._base = settings.BORDERLESS_AUTH_URL.rstrip("/")
        self._secret = settings.BORDERLESS_INTERNAL_SECRET
        self._transport = transport

    async def _get(self, path: str) -> dict:
        async with httpx.AsyncClient(
            base_url=self._base, timeout=_TIMEOUT, transport=self._transport
        ) as client:
            try:
                response = await client.get(path, headers={_HEADER: self._secret})
            except httpx.HTTPError as exc:
                raise LessonCatalogUnavailableError(
                    f"falha ao chamar {path}: {type(exc).__name__}"
                ) from exc
        if response.status_code != 200:
            raise LessonCatalogUnavailableError(
                f"{path} respondeu {response.status_code}"
            )
        return response.json().get("data", {})

    async def list_program_lessons(self, program_slug: str) -> list[CatalogLesson]:
        data = await self._get(f"/api/internal/programs/{program_slug}/lessons")
        return [
            CatalogLesson(
                platform_video_id=row["id"],
                program_slug=row["programSlug"],
                module_slug=row["moduleSlug"],
                video_slug=row["videoSlug"],
                title=row["title"],
                provider=row["provider"],
                provider_ref=row["providerRef"],
                duration_seconds=row.get("durationSeconds"),
            )
            for row in data.get("lessons", [])
        ]

    async def get_media(self, video_id: str) -> LessonMedia:
        data = await self._get(f"/api/internal/videos/{video_id}/media")
        return LessonMedia(
            url=data["url"],
            expires_at=data.get("expiresAt"),
            content_type=data.get("contentType"),
        )
```

Confirme que `DomainError` mora mesmo em `src.support.core.exceptions`
(`grep -n "class DomainError" src/support/core/exceptions.py`).

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/support/clients/test_borderless_lessons_client.py -v`
Expected: PASS — 4 testes

- [ ] **Step 5: Commit**

```bash
git add src/support/clients/borderless/borderless_lessons_client.py tests/unit/support/clients/test_borderless_lessons_client.py
git commit -m "feat(mentor): cliente das rotas internas da borderless-api

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Áudio e transcrição

**Files:**
- Create: `src/support/clients/transcription/__init__.py`, `audio_toolkit.py`, `transcription_client.py`
- Test: `tests/unit/support/clients/test_audio_toolkit.py`, `tests/unit/support/clients/test_transcription_client.py`

**Interfaces:**
- Consumes: `TranscriptSegment` (Task 1), settings do bloco Mentor.
- Produces:
  - `AudioToolkit.extract_audio(source_url: str, dest: Path) -> None`
  - `AudioToolkit.probe_duration(path: Path) -> float`
  - `AudioToolkit.plan_segments(duration: float, window: int) -> list[tuple[float, float]]` — puro, testável sem ffmpeg
  - `AudioToolkit.slice(path: Path, start: float, length: float, dest: Path) -> None`
  - `TranscriptionClient.transcribe(audio_path: Path, prompt: str) -> list[TranscriptSegment]`

- [ ] **Step 1: Escrever o teste da parte pura, que falha**

```python
# tests/unit/support/clients/test_audio_toolkit.py
import pytest

from src.support.clients.transcription.audio_toolkit import AudioToolkit


def test_short_audio_is_a_single_window():
    assert AudioToolkit.plan_segments(duration=120.0, window=600) == [(0.0, 120.0)]


def test_exact_multiple_does_not_produce_an_empty_tail():
    assert AudioToolkit.plan_segments(duration=1200.0, window=600) == [(0.0, 600.0), (600.0, 600.0)]


def test_long_audio_splits_and_keeps_the_remainder():
    assert AudioToolkit.plan_segments(duration=1500.0, window=600) == [
        (0.0, 600.0),
        (600.0, 600.0),
        (1200.0, 300.0),
    ]


def test_zero_duration_yields_nothing_to_transcribe():
    assert AudioToolkit.plan_segments(duration=0.0, window=600) == []


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        AudioToolkit.plan_segments(duration=10.0, window=0)
```

```python
# tests/unit/support/clients/test_transcription_client.py
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.support.clients.transcription.transcription_client import TranscriptionClient


class FakeTranscriptions:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._payload


def fake_openai(payload):
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions(payload)))


@pytest.mark.asyncio
async def test_maps_segments_to_domain_objects(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    payload = SimpleNamespace(segments=[
        SimpleNamespace(text=" olá ", start=0.0, end=2.5),
        SimpleNamespace(text="tokens", start=2.5, end=5.0),
    ])
    client = TranscriptionClient(openai_client=fake_openai(payload))

    segments = await client.transcribe(audio, prompt="Tokens, embeddings")

    assert [s.text for s in segments] == ["olá", "tokens"]
    assert segments[1].start == 2.5 and segments[1].end == 5.0


@pytest.mark.asyncio
async def test_sends_the_glossary_prompt_and_the_language(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    openai = fake_openai(SimpleNamespace(segments=[]))
    client = TranscriptionClient(openai_client=openai)

    await client.transcribe(audio, prompt="autorregressão, tokenização")

    call = openai.audio.transcriptions.calls[0]
    assert call["prompt"] == "autorregressão, tokenização"
    assert call["language"] == "pt"
    assert call["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_a_response_without_segments_yields_an_empty_list(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"fake")
    client = TranscriptionClient(openai_client=fake_openai(SimpleNamespace(segments=None)))
    assert await client.transcribe(audio, prompt="") == []
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/support/clients/test_audio_toolkit.py tests/unit/support/clients/test_transcription_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar**

```python
# src/support/clients/transcription/audio_toolkit.py
"""Wrapper fino de ffmpeg/ffprobe. O planejamento de fatias é puro e separado
da execução para poder ser testado sem o binário instalado."""

import asyncio
import logging
from pathlib import Path

from src.support.core.exceptions import DomainError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


class AudioProcessingError(DomainError):
    """ffmpeg/ffprobe falhou ou não está disponível."""


class AudioToolkit:
    @staticmethod
    def plan_segments(duration: float, window: int) -> list[tuple[float, float]]:
        """Janelas (início, duração) que cobrem o áudio inteiro sem sobra.

        Existe porque a API de transcrição limita o arquivo a 25 MB e uma aula
        de 1h passa disso — sem fatiar, o pipeline quebra exatamente nas aulas
        mais longas (spec §7).
        """
        if window <= 0:
            raise ValueError("window deve ser positivo")
        if duration <= 0:
            return []
        segments: list[tuple[float, float]] = []
        start = 0.0
        while start < duration:
            segments.append((start, min(float(window), duration - start)))
            start += window
        return segments

    @staticmethod
    async def _run(*args: str) -> str:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise AudioProcessingError(
                f"{args[0]} saiu com {process.returncode}: {stderr.decode()[-400:]}"
            )
        return stdout.decode()

    @classmethod
    async def extract_audio(cls, source_url: str, dest: Path) -> None:
        """Mono 16 kHz: o suficiente para fala, e a menor conta possível."""
        await cls._run(
            settings.MENTOR_FFMPEG_BIN, "-y", "-i", source_url,
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dest),
        )

    @classmethod
    async def probe_duration(cls, path: Path) -> float:
        out = await cls._run(
            settings.MENTOR_FFPROBE_BIN, "-v", "error",
            "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        )
        return float(out.strip())

    @classmethod
    async def slice(cls, path: Path, start: float, length: float, dest: Path) -> None:
        await cls._run(
            settings.MENTOR_FFMPEG_BIN, "-y", "-ss", str(start), "-t", str(length),
            "-i", str(path), "-c", "copy", str(dest),
        )
```

```python
# src/support/clients/transcription/transcription_client.py
"""Speech-to-text com timestamps por segmento.

`whisper-1` com `response_format="verbose_json"` devolve `segments` com `start`
e `end` — é o que sustenta a citação "por volta de 12:30" (spec §7). Modelos de
transcrição mais novos têm qualidade melhor mas formato de saída diferente;
antes de trocar `MENTOR_TRANSCRIBE_MODEL`, confirme que o retorno traz segmentos
equivalentes, senão a citação temporal morre silenciosamente.
"""

import logging
from pathlib import Path

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


class TranscriptionClient:
    def __init__(self, openai_client=None) -> None:
        if openai_client is None:
            from openai import AsyncOpenAI

            openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._client = openai_client
        self._model = settings.MENTOR_TRANSCRIBE_MODEL
        self._language = settings.MENTOR_TRANSCRIBE_LANGUAGE

    async def transcribe(self, audio_path: Path, prompt: str) -> list[TranscriptSegment]:
        with audio_path.open("rb") as handle:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=handle,
                language=self._language,
                # Glossário: segura "embedding", "autorregressão", "tokenização".
                prompt=prompt,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        raw = getattr(response, "segments", None) or []
        return [
            TranscriptSegment(
                text=str(getattr(s, "text", "")).strip(),
                start=float(getattr(s, "start", 0.0)),
                end=float(getattr(s, "end", 0.0)),
            )
            for s in raw
        ]
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/support/clients/test_audio_toolkit.py tests/unit/support/clients/test_transcription_client.py -v`
Expected: PASS — 8 testes

- [ ] **Step 5: Verificar o ffmpeg de verdade, uma vez**

```bash
ffmpeg -version | head -1
ffprobe -version | head -1
```

Se faltar, instale (`apt-get install -y ffmpeg`) e acrescente-o ao `docker/`
do repo — a imagem do Oracle precisa dele em runtime. Registre a mudança no
mesmo commit.

- [ ] **Step 6: Commit**

```bash
git add src/support/clients/transcription tests/unit/support/clients/test_audio_toolkit.py tests/unit/support/clients/test_transcription_client.py docker
git commit -m "feat(mentor): extração de áudio e transcrição com timestamps

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: IngestLessonAction — a máquina de estados

**Files:**
- Create: `src/domain/lessons/actions/ingest_lesson_action.py`, `src/domain/lessons/actions/__init__.py`
- Test: `tests/unit/domain/lessons/test_ingest_lesson_action.py`

**Interfaces:**
- Consumes: tudo das Tasks 1 a 5.
- Produces: `IngestLessonAction(embeddings, lessons_client, transcription, lesson_repo=None, chunk_repo=None)` com
  `execute(lesson: Lesson) -> IngestResult`, onde
  `@dataclass(frozen=True) IngestResult(platform_video_id: str, status: TranscriptStatus, chunks: int, skipped: bool, failure_reason: str | None)`

- [ ] **Step 1: Escrever os testes, que falham**

```python
# tests/unit/domain/lessons/test_ingest_lesson_action.py
from pathlib import Path
from uuid import uuid4

import pytest

from src.domain.lessons.actions.ingest_lesson_action import IngestLessonAction
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.enums import TranscriptStatus


class FakeLessonRepo:
    def __init__(self) -> None:
        self.saved: list[Lesson] = []

    async def save(self, lesson: Lesson) -> Lesson:
        self.saved.append(
            Lesson(**{**lesson.__dict__})  # snapshot, não referência viva
        )
        return lesson


class FakeChunkRepo:
    def __init__(self) -> None:
        self.replaced: list[tuple] = []

    async def replace_for_lesson(self, lesson_id, chunks) -> None:
        self.replaced.append((lesson_id, list(chunks)))


class FakeEmbeddings:
    async def embed(self, texts):
        return [[float(i)] * 3 for i, _ in enumerate(texts)]


class FakeClient:
    def __init__(self, url="https://cdn.test/a.m3u8"):
        self.url = url

    async def get_media(self, video_id):
        from src.support.clients.borderless.borderless_lessons_client import LessonMedia

        return LessonMedia(url=self.url, expires_at=None, content_type=None)


class FakeTranscription:
    def __init__(self, segments):
        self._segments = segments

    async def transcribe(self, audio_path: Path, prompt: str):
        return list(self._segments)


def a_lesson(**overrides) -> Lesson:
    base = dict(
        uuid=uuid4(), platform_video_id="v1", program_slug="base",
        module_slug="m1", video_slug="a1", title="Tokens",
        provider="PANDA_VIDEO", provider_ref="ref-1",
    )
    base.update(overrides)
    return Lesson(**base)


def build_action(monkeypatch, segments=None, lesson_repo=None, chunk_repo=None, transcription=None):
    """Neutraliza o ffmpeg: a Task 5 já cobre o toolkit, aqui interessa o fluxo."""
    from src.domain.lessons.actions import ingest_lesson_action as module

    async def fake_extract(source_url, dest):
        Path(dest).write_bytes(b"audio")

    async def fake_probe(path):
        return 100.0

    async def fake_slice(path, start, length, dest):
        Path(dest).write_bytes(b"audio")

    monkeypatch.setattr(module.AudioToolkit, "extract_audio", staticmethod(fake_extract))
    monkeypatch.setattr(module.AudioToolkit, "probe_duration", staticmethod(fake_probe))
    monkeypatch.setattr(module.AudioToolkit, "slice", staticmethod(fake_slice))

    return IngestLessonAction(
        embeddings=FakeEmbeddings(),
        lessons_client=FakeClient(),
        transcription=transcription or FakeTranscription(segments or []),
        lesson_repo=lesson_repo or FakeLessonRepo(),
        chunk_repo=chunk_repo or FakeChunkRepo(),
    )


@pytest.mark.asyncio
async def test_happy_path_reaches_ready_and_writes_chunks(monkeypatch):
    lesson_repo, chunk_repo = FakeLessonRepo(), FakeChunkRepo()
    action = build_action(
        monkeypatch,
        segments=[TranscriptSegment("olá pessoal", 0.0, 2.0), TranscriptSegment("tokens", 2.0, 4.0)],
        lesson_repo=lesson_repo, chunk_repo=chunk_repo,
    )

    result = await action.execute(a_lesson())

    assert result.status == TranscriptStatus.READY
    assert result.chunks == 1
    assert chunk_repo.replaced[0][1][0].start_seconds == 0.0
    assert chunk_repo.replaced[0][1][0].end_seconds == 4.0
    # claim antes do trabalho, ready depois
    assert lesson_repo.saved[0].transcript_status == TranscriptStatus.TRANSCRIBING
    assert lesson_repo.saved[0].attempts == 1
    assert lesson_repo.saved[-1].transcript_status == TranscriptStatus.READY
    assert lesson_repo.saved[-1].failure_reason is None


@pytest.mark.asyncio
async def test_same_hash_skips_the_expensive_half(monkeypatch):
    segments = [TranscriptSegment("mesmo texto", 0.0, 1.0)]
    chunk_repo = FakeChunkRepo()
    action = build_action(monkeypatch, segments=segments, chunk_repo=chunk_repo)

    first = await action.execute(a_lesson())
    second = await action.execute(
        a_lesson(content_hash=first.content_hash, transcript_status=TranscriptStatus.READY)
    )

    assert second.skipped is True
    assert second.status == TranscriptStatus.READY
    assert len(chunk_repo.replaced) == 1  # não re-embedou


@pytest.mark.asyncio
async def test_force_re_embeds_even_with_the_same_hash(monkeypatch):
    segments = [TranscriptSegment("mesmo texto", 0.0, 1.0)]
    chunk_repo = FakeChunkRepo()
    action = build_action(monkeypatch, segments=segments, chunk_repo=chunk_repo)

    first = await action.execute(a_lesson())
    await action.execute(
        a_lesson(content_hash=first.content_hash, transcript_status=TranscriptStatus.READY),
        force=True,
    )

    assert len(chunk_repo.replaced) == 2


@pytest.mark.asyncio
async def test_transcription_failure_marks_failed_and_does_not_raise(monkeypatch):
    class Boom:
        async def transcribe(self, audio_path, prompt):
            raise RuntimeError("provider 503")

    lesson_repo = FakeLessonRepo()
    action = build_action(monkeypatch, transcription=Boom(), lesson_repo=lesson_repo)

    result = await action.execute(a_lesson())

    assert result.status == TranscriptStatus.FAILED
    assert "provider 503" in result.failure_reason
    assert lesson_repo.saved[-1].transcript_status == TranscriptStatus.FAILED
    assert lesson_repo.saved[-1].attempts == 1


@pytest.mark.asyncio
async def test_empty_transcript_is_a_failure_not_a_silent_success(monkeypatch):
    action = build_action(monkeypatch, segments=[])
    result = await action.execute(a_lesson())
    assert result.status == TranscriptStatus.FAILED
    assert "vazia" in result.failure_reason.lower()


@pytest.mark.asyncio
async def test_the_glossary_prompt_carries_the_lesson_title(monkeypatch):
    seen: list[str] = []

    class Spy:
        async def transcribe(self, audio_path, prompt):
            seen.append(prompt)
            return [TranscriptSegment("x", 0.0, 1.0)]

    action = build_action(monkeypatch, transcription=Spy())
    await action.execute(a_lesson(title="Tokens e embeddings"))

    assert "Tokens e embeddings" in seen[0]
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/domain/lessons/test_ingest_lesson_action.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar a Action**

```python
# src/domain/lessons/actions/ingest_lesson_action.py
"""Ingestão de UMA aula: claim → mídia → áudio → fatias → transcrição → hash →
chunks → embeddings → ready.

Cada aula falha sozinha. O `execute` não propaga exceção: ele grava
`failure_reason`, marca `FAILED` e devolve o resultado, para que um lote de 30
aulas não morra por causa de uma (spec §7).
"""

import hashlib
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.domain.lessons.services.transcript_chunking_service import TranscriptChunkingService
from src.support.clients.transcription.audio_toolkit import AudioToolkit
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    platform_video_id: str
    status: TranscriptStatus
    chunks: int
    skipped: bool
    failure_reason: str | None
    content_hash: str | None


class IngestLessonAction:
    def __init__(
        self,
        embeddings,
        lessons_client,
        transcription,
        lesson_repo=None,
        chunk_repo=None,
    ) -> None:
        self.embeddings = embeddings
        self.lessons_client = lessons_client
        self.transcription = transcription
        self.lessons = lesson_repo or LessonRepository()
        self.chunks = chunk_repo or LessonChunkRepository()
        self.chunking = TranscriptChunkingService()

    async def execute(self, lesson: Lesson, force: bool = False) -> IngestResult:
        lesson.transcript_status = TranscriptStatus.TRANSCRIBING
        lesson.attempts += 1
        lesson.failure_reason = None
        await self.lessons.save(lesson)

        try:
            segments = await self._transcribe(lesson)
            if not segments:
                raise ValueError("transcrição vazia — nenhum segmento de fala")

            text = " ".join(s.text for s in segments)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

            if digest == lesson.content_hash and not force:
                lesson.transcript_status = TranscriptStatus.READY
                await self.lessons.save(lesson)
                return IngestResult(
                    lesson.platform_video_id, TranscriptStatus.READY,
                    chunks=0, skipped=True, failure_reason=None, content_hash=digest,
                )

            written = await self._embed_and_store(lesson, segments)

            lesson.transcript_text = text
            lesson.content_hash = digest
            lesson.transcript_status = TranscriptStatus.READY
            lesson.transcribed_at = datetime.now(timezone.utc)
            lesson.failure_reason = None
            await self.lessons.save(lesson)

            return IngestResult(
                lesson.platform_video_id, TranscriptStatus.READY,
                chunks=written, skipped=False, failure_reason=None, content_hash=digest,
            )

        except Exception as exc:  # uma aula ruim não derruba o lote
            logger.exception("falha ao ingerir a aula %s", lesson.platform_video_id)
            reason = f"{type(exc).__name__}: {exc}"[:1000]
            lesson.transcript_status = TranscriptStatus.FAILED
            lesson.failure_reason = reason
            await self.lessons.save(lesson)
            return IngestResult(
                lesson.platform_video_id, TranscriptStatus.FAILED,
                chunks=0, skipped=False, failure_reason=reason, content_hash=lesson.content_hash,
            )

    async def _transcribe(self, lesson: Lesson) -> list[TranscriptSegment]:
        media = await self.lessons_client.get_media(lesson.platform_video_id)
        prompt = self._glossary(lesson)

        with tempfile.TemporaryDirectory(prefix="mentor-") as workdir:
            root = Path(workdir)
            audio = root / "full.mp3"
            await AudioToolkit.extract_audio(media.url, audio)
            duration = await AudioToolkit.probe_duration(audio)

            windows = AudioToolkit.plan_segments(duration, settings.MENTOR_AUDIO_SEGMENT_SECONDS)
            segments: list[TranscriptSegment] = []
            for index, (start, length) in enumerate(windows):
                part = root / f"part-{index}.mp3"
                await AudioToolkit.slice(audio, start, length, part)
                # O modelo só enxerga a fatia, então os tempos voltam zerados:
                # o offset da fatia é somado aqui, não lá.
                segments.extend(s.shifted(start) for s in await self.transcription.transcribe(part, prompt))
            return segments

    @staticmethod
    def _glossary(lesson: Lesson) -> str:
        """Prompt de transcrição: segura os termos técnicos que o modelo erraria
        em português falado (spec §7)."""
        return (
            f"Aula do programa Borderless: {lesson.title}. "
            "Termos técnicos frequentes: embedding, embeddings, tokenização, "
            "autorregressão, autorregressivo, vetor, similaridade, prompt, "
            "LLM, API, deploy, backend, frontend."
        )

    async def _embed_and_store(self, lesson: Lesson, segments: list[TranscriptSegment]) -> int:
        pieces = self.chunking.split(segments)
        vectors = await self.embeddings.embed([text for text, _, _ in pieces])
        entities = [
            LessonChunk(
                uuid=uuid4(),
                lesson_id=lesson.uuid,
                ordinal=i,
                content=text,
                start_seconds=start,
                end_seconds=end,
                embedding=vectors[i],
            )
            for i, (text, start, end) in enumerate(pieces)
        ]
        await self.chunks.replace_for_lesson(lesson.uuid, entities)
        return len(entities)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/domain/lessons/test_ingest_lesson_action.py -v`
Expected: PASS — 6 testes

- [ ] **Step 5: Commit**

```bash
git add src/domain/lessons/actions tests/unit/domain/lessons/test_ingest_lesson_action.py
git commit -m "feat(mentor): máquina de estados da ingestão de uma aula

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Comando `mentor:ingest`

**Files:**
- Create: `src/domain/lessons/actions/sync_program_lessons_action.py`
- Create: `src/app/console/commands/mentor_ingest_command.py`
- Test: `tests/unit/domain/lessons/test_sync_program_lessons_action.py`, `tests/unit/app/console/test_mentor_ingest_command.py`

**Interfaces:**
- Consumes: tudo das Tasks 1 a 6.
- Produces:
  - `SyncProgramLessonsAction(lessons_client, lesson_repo=None).execute(program_slug: str) -> list[Lesson]`
  - `MentorIngestCommand` com signature
    `mentor:ingest {program:str} {--lesson:str=} {--force:bool} {--limit:int=}`

- [ ] **Step 1: Escrever o teste do sync, que falha**

```python
# tests/unit/domain/lessons/test_sync_program_lessons_action.py
import pytest

from src.domain.lessons.actions.sync_program_lessons_action import SyncProgramLessonsAction
from src.support.clients.borderless.borderless_lessons_client import CatalogLesson


class FakeClient:
    def __init__(self, rows):
        self._rows = rows

    async def list_program_lessons(self, program_slug):
        return self._rows


class FakeRepo:
    def __init__(self):
        self.upserted = []

    async def upsert_from_catalog(self, lesson):
        self.upserted.append(lesson)
        return lesson


def row(video_id="v1") -> CatalogLesson:
    return CatalogLesson(
        platform_video_id=video_id, program_slug="base", module_slug="m1",
        video_slug=f"aula-{video_id}", title="Tokens", provider="PANDA_VIDEO",
        provider_ref=f"ref-{video_id}", duration_seconds=None,
    )


@pytest.mark.asyncio
async def test_every_catalog_row_becomes_an_upsert():
    repo = FakeRepo()
    action = SyncProgramLessonsAction(lessons_client=FakeClient([row("v1"), row("v2")]), lesson_repo=repo)

    lessons = await action.execute("base")

    assert [l.platform_video_id for l in lessons] == ["v1", "v2"]
    assert len(repo.upserted) == 2


@pytest.mark.asyncio
async def test_new_lessons_start_pending():
    from src.domain.lessons.enums import TranscriptStatus

    action = SyncProgramLessonsAction(lessons_client=FakeClient([row()]), lesson_repo=FakeRepo())
    lessons = await action.execute("base")
    assert lessons[0].transcript_status == TranscriptStatus.PENDING


@pytest.mark.asyncio
async def test_an_empty_catalog_is_not_an_error():
    action = SyncProgramLessonsAction(lessons_client=FakeClient([]), lesson_repo=FakeRepo())
    assert await action.execute("base") == []
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `uv run pytest tests/unit/domain/lessons/test_sync_program_lessons_action.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implementar o sync**

```python
# src/domain/lessons/actions/sync_program_lessons_action.py
"""Reconcilia o catálogo de aulas da plataforma com a tabela `lessons`.

Só escreve campos de catálogo: o `upsert_from_catalog` do repositório preserva
estado de transcrição de propósito, para que re-sincronizar não jogue fora
trabalho já feito.
"""

from uuid import uuid4

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_repository import LessonRepository


class SyncProgramLessonsAction:
    def __init__(self, lessons_client, lesson_repo=None) -> None:
        self.lessons_client = lessons_client
        self.lessons = lesson_repo or LessonRepository()

    async def execute(self, program_slug: str) -> list[Lesson]:
        rows = await self.lessons_client.list_program_lessons(program_slug)
        result: list[Lesson] = []
        for row in rows:
            result.append(
                await self.lessons.upsert_from_catalog(
                    Lesson(
                        uuid=uuid4(),
                        platform_video_id=row.platform_video_id,
                        program_slug=row.program_slug,
                        module_slug=row.module_slug,
                        video_slug=row.video_slug,
                        title=row.title,
                        duration_seconds=row.duration_seconds,
                        provider=row.provider,
                        provider_ref=row.provider_ref,
                        transcript_status=TranscriptStatus.PENDING,
                    )
                )
            )
        return result
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest tests/unit/domain/lessons/test_sync_program_lessons_action.py -v`
Expected: PASS — 3 testes

- [ ] **Step 5: Escrever o comando**

```python
# src/app/console/commands/mentor_ingest_command.py
from src.domain.lessons.actions.ingest_lesson_action import IngestLessonAction
from src.domain.lessons.actions.sync_program_lessons_action import SyncProgramLessonsAction
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.clients.borderless.borderless_lessons_client import BorderlessLessonsClient
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.clients.transcription.transcription_client import TranscriptionClient
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal
from src.support.core.settings import settings


class MentorIngestCommand(Command):
    signature = "mentor:ingest {program:str} {--lesson:str=} {--force:bool} {--limit:int=}"
    description = "Transcreve e indexa as aulas de um programa para o mentor de aula."

    def __init__(self, lessons_client=None, transcription=None) -> None:
        super().__init__()
        # Injetáveis em teste; o autodiscovery do kernel instancia sem argumento,
        # então os defaults precisam bastar.
        self._lessons_client = lessons_client or BorderlessLessonsClient()
        self._transcription = transcription or TranscriptionClient()

    async def handle(self) -> None:
        program = self.input["program"]
        only = self.input.get("lesson")
        force = bool(self.input.get("force"))
        limit = self.input.get("limit")

        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                sync = SyncProgramLessonsAction(lessons_client=self._lessons_client)
                await sync.execute(program)
                await session.commit()

                repo = LessonRepository()
                if only:
                    every = await repo.list_pending(program, max_attempts=settings.MENTOR_MAX_ATTEMPTS)
                    targets = [l for l in every if l.video_slug == only]
                    if not targets and force:
                        found = None
                        for candidate in await repo.list_pending(program, max_attempts=10**6):
                            if candidate.video_slug == only:
                                found = candidate
                        targets = [found] if found else []
                else:
                    targets = await repo.list_pending(program, max_attempts=settings.MENTOR_MAX_ATTEMPTS)

                if limit:
                    targets = targets[:limit]

                action = IngestLessonAction(
                    embeddings=get_embeddings_client(),
                    lessons_client=self._lessons_client,
                    transcription=self._transcription,
                )

                done, skipped, failed = 0, 0, []
                for lesson in targets:
                    result = await action.execute(lesson, force=force)
                    # Commit por aula: um lote longo não pode perder tudo se a
                    # aula 28 derrubar o processo.
                    await session.commit()
                    if result.status == TranscriptStatus.FAILED:
                        failed.append((result.platform_video_id, result.failure_reason))
                    elif result.skipped:
                        skipped += 1
                    else:
                        done += 1
                    print(
                        f"  {lesson.video_slug}: {result.status}"
                        f"{' (sem mudança)' if result.skipped else f' — {result.chunks} chunks'}"
                    )

                print(f"\n{program}: {done} transcritas, {skipped} sem mudança, {len(failed)} falhas")
                for video_id, reason in failed:
                    print(f"  FALHA {video_id}: {reason}")
            except Exception:
                await session.rollback()
                raise
            finally:
                CurrentAsyncSessionContext.clear()
```

Confirme o autodiscovery: abra `cli.py` e veja como ele encontra os comandos de
`src/app/console/commands/`. Se exigir registro explícito, registre.

- [ ] **Step 6: Escrever o teste do comando**

```python
# tests/unit/app/console/test_mentor_ingest_command.py
from src.app.console.commands.mentor_ingest_command import MentorIngestCommand


def test_command_name_and_signature():
    assert MentorIngestCommand.name() == "mentor:ingest"
    assert "{program:str}" in MentorIngestCommand.signature
    assert "{--force:bool}" in MentorIngestCommand.signature


def test_parses_program_and_flags():
    command = MentorIngestCommand()
    command.input = command.parse(["base", "--lesson", "aula-1", "--force"])
    assert command.input["program"] == "base"
    assert command.input["lesson"] == "aula-1"
    assert command.input["force"] is True


def test_force_defaults_to_false():
    command = MentorIngestCommand()
    command.input = command.parse(["base"])
    assert command.input["force"] is False
```

Abra `tests/unit/app/console/test_knowledge_ingest_command.py` e use **o mesmo
mecanismo** de parse que ele usa — se o método não se chamar `parse`, ajuste os
três testes para o nome real.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `uv run pytest tests/unit/domain/lessons tests/unit/app/console tests/unit/support/clients -v`
Expected: PASS

Run: `uv run pytest tests/integration/domain/lessons -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/domain/lessons/actions/sync_program_lessons_action.py src/app/console/commands/mentor_ingest_command.py tests/unit/domain/lessons/test_sync_program_lessons_action.py tests/unit/app/console/test_mentor_ingest_command.py
git commit -m "feat(mentor): comando mentor:ingest

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Verificação final do plano

Com a `borderless-api` rodando local, `BORDERLESS_INTERNAL_SECRET` batendo com o
`MENTOR_INGEST_SECRET` de lá, e `OPENAI_API_KEY` no `.env`:

```bash
uv run python cli.py mentor:ingest base --lesson <slug-de-uma-aula-curta>
```

Esperado: uma linha `ready — N chunks`. Depois, no banco:

```sql
SELECT title, transcript_status, attempts, length(transcript_text) FROM lessons;
SELECT ordinal, start_seconds, end_seconds, left(content, 60) FROM lesson_chunks ORDER BY ordinal LIMIT 5;
```

Os `start_seconds` precisam crescer monotonicamente e o primeiro precisa ser
próximo de 0. Se todos vierem 0, o offset das fatias não está sendo somado —
o bug mora em `IngestLessonAction._transcribe`.

Rode o comando **duas vezes** e confirme que a segunda diz `sem mudança`: é a
prova da idempotência por `content_hash`.

Só então rode o lote completo (fase 4 da spec), que é o que deixa o mentor ativo
em todas as aulas do Base:

```bash
uv run python cli.py mentor:ingest base
```

Espere na ordem de US$10 e algumas dezenas de minutos. O relatório final diz
quantas transcreveram, quantas ficaram sem mudança e quais falharam com que
motivo. Aulas em `failed` podem ser re-tentadas rodando o comando de novo — elas
voltam ao lote enquanto tiverem tentativa sobrando. Confira o saldo no banco:

```sql
SELECT transcript_status, count(*) FROM lessons WHERE program_slug = 'base' GROUP BY 1;
```
