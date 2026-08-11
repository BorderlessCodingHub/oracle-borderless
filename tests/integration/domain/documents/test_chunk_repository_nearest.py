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
    # Documento SEM procedência (kb_root_page_id=None): sem a guarda fail-closed,
    # `DocumentModel.kb_root_page_id == root` degeneraria para `IS NULL` (já que
    # `normalize_page_id(None)` é `None`), e este documento passaria a bater —
    # exatamente o vazamento que o comentário em `search_similar` descreve.
    # Semear um doc com kb_root_page_id=ROOT (válido) não prenderia essa guarda,
    # pois ele ficaria fora do resultado de qualquer forma, com ou sem o early
    # return.
    await seed_document_with_chunk("sem procedência", kb_root_page_id=None)
    repo = DocumentChunkRepository()
    assert await repo.nearest_distance(_vector(1.0)) is None
