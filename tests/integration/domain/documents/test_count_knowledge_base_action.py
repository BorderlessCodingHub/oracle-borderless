"""Contagens da base (ADR-0015): não há mais escopo por procedência nas
leituras — documento de qualquer root entra em qualquer contador, contanto
que aprovado (`status == "approved"`) e não removido (`deleted_at IS NULL`).
O que os contadores continuam distinguindo é status e soft-delete, não root."""

import pytest

from src.domain.documents.actions.count_knowledge_base_action import (
    CountKnowledgeBaseAction,
)

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"


@pytest.mark.asyncio
async def test_documents_active_counts_regardless_of_root(seed_document_with_chunk):
    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 2


@pytest.mark.asyncio
async def test_documents_archived_counts_soft_deleted_regardless_of_root(
    seed_document_with_chunk,
):
    await seed_document_with_chunk(title="Viva", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Morta do root atual", kb_root_page_id=ROOT, soft_deleted=True)
    await seed_document_with_chunk(
        title="Morta de outro root", kb_root_page_id=OUTRO_ROOT, soft_deleted=True
    )

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 1
    assert counts.documents_archived == 2


@pytest.mark.asyncio
async def test_chunks_counts_active_chunks_regardless_of_root(seed_document_with_chunk):
    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)
    await seed_document_with_chunk(title="Removida", kb_root_page_id=ROOT, soft_deleted=True)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.chunks == 2


@pytest.mark.asyncio
async def test_counts_include_documents_without_provenance(seed_document_with_chunk):
    """Documento sem `kb_root_page_id` gravado conta normalmente — não há mais
    convenção fail-closed amarrada à configuração de roots."""
    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 1
    assert counts.documents_archived == 0
    assert counts.chunks == 1
