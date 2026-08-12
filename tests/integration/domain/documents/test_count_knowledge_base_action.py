"""Escopo nas contagens da base (ADR-0012): documento fora do root vigente não
soma em nenhum contador, mesmo que ainda esteja ativo no banco — ver review
da Task 6, onde a versão inicial contava sem esse filtro."""

import pytest

from src.domain.documents.actions.count_knowledge_base_action import (
    CountKnowledgeBaseAction,
)
from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"


@pytest.mark.asyncio
async def test_documents_active_counts_only_the_current_root(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 1


@pytest.mark.asyncio
async def test_documents_archived_counts_soft_deleted_of_the_current_root(
    monkeypatch, seed_document_with_chunk
):
    """`documents_archived` é escopado ao root vigente, simétrico a
    `documents_active` — ver a justificativa completa no docstring de
    `DocumentRepository.count_archived`."""
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    await seed_document_with_chunk(title="Viva", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Morta do root atual", kb_root_page_id=ROOT, soft_deleted=True)
    await seed_document_with_chunk(
        title="Morta de outro root", kb_root_page_id=OUTRO_ROOT, soft_deleted=True
    )

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 1
    assert counts.documents_archived == 1


@pytest.mark.asyncio
async def test_chunks_counts_only_chunks_in_scope(monkeypatch, seed_document_with_chunk):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)
    await seed_document_with_chunk(title="Removida", kb_root_page_id=ROOT, soft_deleted=True)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.chunks == 1


@pytest.mark.asyncio
async def test_counts_degrade_to_zero_when_root_is_unconfigured(
    monkeypatch, seed_document_with_chunk
):
    """Mesma convenção fail-closed de `list_sections`/`search_similar`: sem
    root configurado, zero — nunca o total do banco sem procedência."""
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    counts = await CountKnowledgeBaseAction().execute()

    assert counts.documents_active == 0
    assert counts.documents_archived == 0
    assert counts.chunks == 0
