"""Limiar de distância: chunk distante demais não vira contexto."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_returns_nothing_when_everything_is_beyond_the_threshold(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "RAG_MAX_DISTANCE", 0.05, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    # embedding do chunk é [1.0, 0, 0, ...]; a query é o oposto -> distância ~2.0
    await seed_document_with_chunk(
        title="Distante", kb_root_page_id=ROOT, embedding=[1.0] + [0.0] * 1535
    )
    query = [-1.0] + [0.0] * 1535

    assert await DocumentChunkRepository().search_similar(query, top_k=10) == []


@pytest.mark.asyncio
async def test_returns_the_chunk_when_within_the_threshold(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "RAG_MAX_DISTANCE", 0.55, raising=False)
    from src.domain.documents.repositories.document_chunk_repository import (
        DocumentChunkRepository,
    )

    await seed_document_with_chunk(
        title="Próximo", kb_root_page_id=ROOT, embedding=[1.0] + [0.0] * 1535
    )
    query = [1.0] + [0.0] * 1535  # idêntico -> distância ~0

    hits = await DocumentChunkRepository().search_similar(query, top_k=10)
    assert [h.citation.title for h in hits] == ["Próximo"]
