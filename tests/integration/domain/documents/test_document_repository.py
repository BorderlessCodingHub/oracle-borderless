from datetime import datetime
from uuid import uuid4

import pytest

from src.domain.documents.entities.document import Document
from src.domain.documents.repositories.document_repository import DocumentRepository


def _doc(page_id, title="T"):
    now = datetime(2026, 1, 1)
    return Document(uuid4(), page_id, title, "conteúdo", "https://n", "approved", now, now, None)


def _doc_with_provenance(page_id, title, kb_root_page_id, kb_section):
    now = datetime(2026, 1, 1)
    return Document(
        uuid4(),
        page_id,
        title,
        "conteúdo",
        "https://n",
        "approved",
        now,
        now,
        None,
        None,
        kb_root_page_id,
        kb_section,
    )


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates(db_session):
    repo = DocumentRepository()
    created = await repo.upsert(_doc("pid-1", "Original"))
    await db_session.flush()
    assert created.title == "Original"

    updated = await repo.upsert(_doc("pid-1", "Atualizado"))
    await db_session.flush()

    found = await repo.get_by_notion_page_id("pid-1")
    assert found is not None
    assert found.title == "Atualizado"
    assert found.uuid == created.uuid  # mesma linha, não duplicou


@pytest.mark.asyncio
async def test_upsert_updates_kb_provenance_on_existing_document(db_session):
    """Re-sync de um documento existente precisa regravar kb_root_page_id/kb_section.

    Regressão: se a tupla de chaves do update em `upsert` não incluir esses campos,
    a procedência gravada no primeiro insert nunca é atualizada em re-syncs.
    """
    repo = DocumentRepository()
    created = await repo.upsert(
        _doc_with_provenance("pid-2", "Original", "root-a", "section-a")
    )
    await db_session.flush()
    assert created.kb_root_page_id == "root-a"
    assert created.kb_section == "section-a"

    updated = await repo.upsert(
        _doc_with_provenance("pid-2", "Original", "root-b", "section-b")
    )
    await db_session.flush()
    assert updated.kb_root_page_id == "root-b"
    assert updated.kb_section == "section-b"

    found = await repo.get_by_notion_page_id("pid-2")
    assert found is not None
    assert found.kb_root_page_id == "root-b"
    assert found.kb_section == "section-b"
