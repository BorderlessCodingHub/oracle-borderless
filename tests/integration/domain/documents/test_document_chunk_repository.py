from datetime import datetime
from uuid import uuid4

import pytest

from src.domain.documents.entities.document import Document
from src.domain.documents.entities.document_chunk import DocumentChunk
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.domain.documents.repositories.document_chunk_repository import DocumentChunkRepository
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id

DIM = 1536
# Literal fixo (não lido de settings ao vivo): se NOTION_KB_ROOT_PAGE_ID nunca
# estivesse setado em ambiente algum, `normalize_page_id(settings...)` viraria
# None e — via o guard-clause do repository — o teste continuaria passando
# sem de fato exercitar o filtro de escopo.
ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
NORMALIZED_ROOT = normalize_page_id(ROOT)


def _vec(seed: float):
    return [seed] + [0.0] * (DIM - 1)


@pytest.mark.asyncio
async def test_search_similar_returns_nearest_approved(db_session, monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    now = datetime(2026, 1, 1)
    doc = await DocumentRepository().upsert(
        Document(
            uuid4(), f"pid-{uuid4()}", "Regras", "c", "https://n", "approved", now, now, None,
            kb_root_page_id=NORMALIZED_ROOT,
        )
    )
    await db_session.flush()

    chunk_repo = DocumentChunkRepository()
    await chunk_repo.replace_for_document(
        doc.uuid,
        [
            DocumentChunk(uuid4(), doc.uuid, 0, "trecho perto", _vec(1.0)),
            DocumentChunk(uuid4(), doc.uuid, 1, "trecho longe", _vec(-1.0)),
        ],
    )
    await db_session.flush()

    hits = await chunk_repo.search_similar(_vec(1.0), top_k=1)
    assert len(hits) == 1
    assert hits[0].content == "trecho perto"
    assert hits[0].citation.title == "Regras"
    assert hits[0].citation.is_notion()


@pytest.mark.asyncio
async def test_search_similar_excludes_non_approved_and_deleted(db_session, monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    now = datetime(2026, 1, 1)

    approved_doc = await DocumentRepository().upsert(
        Document(
            uuid4(), f"pid-{uuid4()}", "Regras Aprovadas", "c", "https://n", "approved", now, now, None,
            kb_root_page_id=NORMALIZED_ROOT,
        )
    )
    pending_doc = await DocumentRepository().upsert(
        Document(
            uuid4(), f"pid-{uuid4()}", "Rascunho Pendente", "c", "https://n", "pending", now, now, None,
            kb_root_page_id=NORMALIZED_ROOT,
        )
    )
    deleted_doc = await DocumentRepository().upsert(
        Document(
            uuid4(), f"pid-{uuid4()}", "Documento Removido", "c", "https://n", "approved", now, now, now,
            kb_root_page_id=NORMALIZED_ROOT,
        )
    )
    await db_session.flush()

    chunk_repo = DocumentChunkRepository()
    # Approved chunk is FAR from the query vector.
    await chunk_repo.replace_for_document(
        approved_doc.uuid,
        [DocumentChunk(uuid4(), approved_doc.uuid, 0, "trecho aprovado", _vec(-1.0))],
    )
    # Pending and soft-deleted chunks are CLOSE to the query vector (nearest neighbors).
    await chunk_repo.replace_for_document(
        pending_doc.uuid,
        [DocumentChunk(uuid4(), pending_doc.uuid, 0, "trecho pendente", _vec(1.0))],
    )
    await chunk_repo.replace_for_document(
        deleted_doc.uuid,
        [DocumentChunk(uuid4(), deleted_doc.uuid, 0, "trecho deletado", _vec(1.0))],
    )
    await db_session.flush()

    hits = await chunk_repo.search_similar(_vec(1.0), top_k=5)

    contents = [hit.content for hit in hits]
    assert "trecho pendente" not in contents
    assert "trecho deletado" not in contents
    assert contents == ["trecho aprovado"]
