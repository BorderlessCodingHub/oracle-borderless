from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.repositories.conversation_repository import (
    ConversationRepository,
)
from src.domain.documents.entities.document import Document
from src.domain.documents.entities.document_chunk import DocumentChunk
from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(settings.database_url_async_test, poolclass=None)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        CurrentAsyncSessionContext.set(session)
        try:
            yield session
            await session.rollback()
        finally:
            CurrentAsyncSessionContext.clear()
    await engine.dispose()


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


@pytest.fixture
def seed_traces(db_session):
    """Insere linhas de `agent_traces` a partir de dicts parciais.

    Cada dict só precisa dos campos que o teste se importa (`question`,
    `outcome`, `retrieval_best_distance`, ...) — os demais NOT NULL levam o
    default da Entity `TurnTrace`. Todas as linhas de uma chamada penduram na
    mesma `Conversation`, criada sob demanda; o rollback do `db_session` limpa
    tudo no fim do teste.
    """

    async def _seed(rows: list[dict]) -> list[TurnTrace]:
        now = datetime.now(timezone.utc)
        conversation = await ConversationRepository().create(
            Conversation(uuid=uuid7(), user_email=None, title="t", created_at=now, updated_at=now, deleted_at=None)
        )
        await db_session.flush()

        repo = TurnTraceRepository()
        traces = []
        for row in rows:
            attrs = dict(
                uuid=uuid7(),
                conversation_id=conversation.uuid,
                question="q",
                outcome="answer",
                created_at=now,
            )
            attrs.update(row)
            traces.append(await repo.append(TurnTrace(**attrs)))
        await db_session.flush()
        return traces

    return _seed


@pytest.fixture
def seed_trace(db_session):
    """Insere uma linha de `agent_traces` por chamada, com kwargs soltos.

    Complemento a `seed_traces` (lista de dicts) para testes que preferem uma
    linha por chamada — caso das leituras do mentor (`GetMentorInsightsAction`),
    onde cada `await seed_trace(intent=..., lesson_id=..., ...)` lê melhor como
    "esta pergunta aconteceu assim". Mesmas regras: os campos não passados
    levam o default da Entity `TurnTrace`, cada chamada cria sua própria
    `Conversation`, e o rollback do `db_session` limpa tudo no fim do teste.
    """

    async def _seed(**kwargs) -> TurnTrace:
        now = datetime.now(timezone.utc)
        conversation = await ConversationRepository().create(
            Conversation(uuid=uuid7(), user_email=None, title="t", created_at=now, updated_at=now, deleted_at=None)
        )
        await db_session.flush()

        attrs = dict(
            uuid=uuid7(),
            conversation_id=conversation.uuid,
            question="q",
            outcome="answer",
            created_at=now,
            # "base" é o `program_slug` de convenção nos testes deste repo
            # (ver `test_mentor_trace.py`) — default sensato para quem chama
            # `seed_trace` sem se importar com qual programa é.
            program_slug="base",
        )
        attrs.update(kwargs)
        trace = await TurnTraceRepository().append(TurnTrace(**attrs))
        await db_session.flush()
        return trace

    return _seed
