from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.entities.document import Document
from src.domain.documents.models.document_chunk import DocumentChunkModel
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.domain.documents.services.chunking_service import ChunkingService
from src.support.core.exceptions import DomainError
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id
from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

# Literal fixo (não lido de settings ao vivo): se NOTION_KB_ROOT_PAGE_IDS nunca
# estivesse setado em ambiente algum, `normalize_page_id(settings...)` viraria
# None e — via o guard-clause do repository — o teste continuaria passando
# sem de fato exercitar o filtro de escopo.
ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
NORMALIZED_ROOT = normalize_page_id(ROOT)


@pytest.mark.asyncio
async def test_ingest_persists_document_and_chunks(db_session, monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    # Neutralize RAG_MAX_DISTANCE at its bound (cosine distance is capped at
    # 2.0) so this test doesn't break if someone lowers the threshold in
    # `.env` — it's testing persistence + retrievability, not the distance
    # filter itself.
    monkeypatch.setattr(settings, "RAG_MAX_DISTANCE", 2.0, raising=False)
    now = datetime(2026, 1, 1)
    long_content = "parágrafo. " * 400  # força múltiplos chunks
    doc = Document(
        uuid4(), f"pid-{uuid4()}", "Guia", long_content, "https://n", "approved", now, now, None,
        kb_root_page_id=NORMALIZED_ROOT,
    )

    action = IngestDocumentAction(embeddings=FakeEmbeddingsClient())
    persisted = await action.execute(doc)
    await db_session.flush()

    assert persisted.notion_page_id == doc.notion_page_id
    hits = await DocumentChunkRepository().search_similar([0.1] * 1536, top_k=5)
    assert len(hits) >= 1


@pytest.mark.asyncio
async def test_ingest_cleans_notion_markup_before_chunking(db_session):
    """A ingestão limpa a sintaxe custom do Notion; nenhum chunk persiste markup cru."""
    now = datetime(2026, 1, 1)
    page_id = f"pid-{uuid4()}"
    content = (
        '## Guia {toggle="true"}\n'
        '<callout icon="▶️" color="gray_bg">\nPasso importante do processo.\n</callout>\n'
        "<empty-block/>"
    )
    doc = Document(uuid4(), page_id, "Guia", content, "https://n", "approved", now, now, None)

    persisted = await IngestDocumentAction(embeddings=FakeEmbeddingsClient()).execute(doc)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(DocumentChunkModel.content).where(DocumentChunkModel.document_id == persisted.uuid)
        )
    ).scalars().all()
    assert rows, "esperava ao menos um chunk"
    blob = "\n".join(rows)
    assert "<callout" not in blob and "<empty-block" not in blob and "{toggle" not in blob
    assert "Passo importante do processo." in blob


@pytest.mark.asyncio
async def test_ingest_rejects_non_approved_document(db_session):
    """Regra 4 (base de conhecimento): documento não aprovado não pode ser ingerido nem persistido."""
    now = datetime(2026, 1, 1)
    page_id = f"pid-{uuid4()}"
    doc = Document(uuid4(), page_id, "Rascunho", "conteúdo qualquer", "https://n", "pending", now, now, None)

    action = IngestDocumentAction(embeddings=FakeEmbeddingsClient())
    with pytest.raises(DomainError):
        await action.execute(doc)
    await db_session.flush()

    persisted = await DocumentRepository().get_by_notion_page_id(page_id)
    assert persisted is None


@pytest.mark.asyncio
async def test_ingest_is_idempotent_and_replaces_chunks(db_session, monkeypatch):
    """Re-ingerir a mesma notion_page_id deve atualizar o documento in place e substituir os chunks, sem acumular."""
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    now = datetime(2026, 1, 1)
    page_id = f"pid-{uuid4()}"
    old_content = "conteúdo antigo sobre regras antigas. " * 400
    new_content = "conteúdo novo totalmente diferente sobre políticas atuais. " * 400

    action = IngestDocumentAction(embeddings=FakeEmbeddingsClient())

    first_doc = Document(
        uuid4(), page_id, "Guia", old_content, "https://n", "approved", now, now, None,
        kb_root_page_id=NORMALIZED_ROOT,
    )
    first = await action.execute(first_doc)
    await db_session.flush()

    second_doc = Document(
        uuid4(), page_id, "Guia", new_content, "https://n", "approved", now, now, None,
        kb_root_page_id=NORMALIZED_ROOT,
    )
    second = await action.execute(second_doc)
    await db_session.flush()

    # upsert: mesma linha (mesmo uuid), não uma linha nova/duplicada.
    assert second.uuid == first.uuid
    assert second.content == new_content

    # chunks substituídos, não acumulados: total de chunks == chunks do conteúdo novo.
    expected_chunks = ChunkingService().split(new_content)
    count_stmt = select(func.count()).select_from(DocumentChunkModel).where(
        DocumentChunkModel.document_id == second.uuid
    )
    total_chunks = (await db_session.execute(count_stmt)).scalar_one()
    assert total_chunks == len(expected_chunks)

    # nenhum chunk remanescente do conteúdo antigo.
    vector = FakeEmbeddingsClient()._vector(expected_chunks[0])
    hits = await DocumentChunkRepository().search_similar(vector, top_k=len(expected_chunks) + 5)
    assert len(hits) == len(expected_chunks)
    assert all("antigo" not in hit.content for hit in hits)
    assert all("novo" in hit.content for hit in hits)
