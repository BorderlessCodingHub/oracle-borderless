"""Recuperação sem filtro de procedência (ADR-0015): o escopo é a permissão do
Notion, aplicada na descoberta e na reconciliação — não uma comparação de
`kb_root_page_id` no SQL de leitura. O que sobrevive aqui é `deleted_at`."""

import pytest

from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)

UM_ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"
OUTRO_ROOT = "99998d655-c889-81cb-aa18-c2a7701"

# Vetor NÃO-nulo: cosine_distance contra vetor zero é indefinida (NaN no pgvector)
# e tornaria a ordenação — e o limiar — imprevisíveis.
_QUERY = [1.0] + [0.0] * 1535


@pytest.mark.asyncio
async def test_provenance_no_longer_filters_retrieval(seed_document_with_chunk):
    await seed_document_with_chunk(title="De um root", kb_root_page_id=UM_ROOT)
    await seed_document_with_chunk(title="De outro root", kb_root_page_id=OUTRO_ROOT)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert {"De um root", "De outro root"} <= {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_document_without_provenance_is_retrievable(seed_document_with_chunk):
    # Antes: `IN (roots)` excluía NULL, e sem roots a guarda fail-closed
    # devolvia [] para tudo. Sem filtro, o documento entra normalmente.
    await seed_document_with_chunk(title="Sem procedência", kb_root_page_id=None)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    assert "Sem procedência" in {h.citation.title for h in hits}


@pytest.mark.asyncio
async def test_soft_deleted_document_is_still_excluded(seed_document_with_chunk):
    # A garantia que SOBREVIVE: a reconciliação do sync continua sendo o que
    # tira documento de circulação. Semeia também um documento vivo de
    # controle: sem ele, o teste passaria igual se `search_similar` devolvesse
    # `[]` por qualquer outro motivo — a asserção positiva é o que garante que
    # estamos de fato testando a exclusão do soft-deletado, não um retorno vazio.
    await seed_document_with_chunk(
        title="Despublicada", kb_root_page_id=UM_ROOT, soft_deleted=True
    )
    await seed_document_with_chunk(title="Ativa", kb_root_page_id=UM_ROOT)

    hits = await DocumentChunkRepository().search_similar(_QUERY, top_k=10)

    titles = {h.citation.title for h in hits}
    assert "Despublicada" not in titles
    assert "Ativa" in titles


@pytest.mark.asyncio
async def test_nearest_distance_ignores_provenance_too(seed_document_with_chunk):
    # `nearest_distance` serve o trace do caminho de recusa e tinha a mesma
    # guarda fail-closed: sem roots, devolvia None.
    await seed_document_with_chunk(title="Qualquer", kb_root_page_id=OUTRO_ROOT)

    assert await DocumentChunkRepository().nearest_distance(_QUERY) is not None
