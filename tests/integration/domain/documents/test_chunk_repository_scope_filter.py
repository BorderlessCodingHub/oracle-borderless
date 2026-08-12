"""Escopo na recuperação: documento de outro root não é recuperado (ADR-0012)."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"

# Vetor NÃO-nulo: cosine_distance contra vetor zero é indefinida (NaN no pgvector)
# e tornaria a ordenação — e o limiar da Task 5 — imprevisíveis.
_QUERY = [1.0] + [0.0] * 1535


@pytest.mark.asyncio
async def test_chunk_of_another_root_is_not_retrieved(monkeypatch, seed_document_with_chunk):
    """`seed_document_with_chunk(kb_root_page_id=...)` insere doc + 1 chunk."""
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Do root atual", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)
    titles = {h.citation.title for h in hits}

    assert "Do root atual" in titles
    assert "De outro root" not in titles


@pytest.mark.asyncio
async def test_document_without_provenance_is_not_retrieved(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)
    assert "Sem procedência" not in {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_search_similar_returns_empty_when_root_unconfigured(
    monkeypatch, seed_document_with_chunk
):
    """Sem root configurado, a busca degrada para 'sem conhecimento' (lista vazia).

    `DocumentModel.kb_root_page_id == None` compilaria para `IS NULL`, que
    combina exatamente com os documentos sem procedência — o guard-clause em
    `search_similar` existe para que a ausência de configuração nunca vire um
    "libera tudo sem procedência" por acidente.
    """
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)
    assert hits == []


@pytest.mark.asyncio
async def test_search_similar_returns_documents_from_every_configured_root(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(
        settings, "NOTION_KB_ROOT_PAGE_IDS", f"{ROOT},{OUTRO_ROOT}", raising=False
    )
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Do root A", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Do root B", kb_root_page_id=OUTRO_ROOT)

    results = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert {r.citation.title for r in results} == {"Do root A", "Do root B"}


@pytest.mark.asyncio
async def test_search_similar_excludes_root_outside_the_allowlist(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(title="Dentro", kb_root_page_id=ROOT)
    await seed_document_with_chunk(title="Fora", kb_root_page_id=OUTRO_ROOT)

    results = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert {r.citation.title for r in results} == {"Dentro"}
