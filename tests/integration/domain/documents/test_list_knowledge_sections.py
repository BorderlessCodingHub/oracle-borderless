"""Lista de temas que o oráculo cobre — alimenta a mensagem de recusa."""

import pytest

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_lists_distinct_sections_sorted(seed_document_with_chunk):
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="d1", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(title="d2", kb_root_page_id=ROOT, kb_section="Bootcamps")
    await seed_document_with_chunk(title="d3", kb_root_page_id=ROOT, kb_section="Programs")

    assert await ListKnowledgeSectionsAction().execute() == ["Bootcamps", "Programs"]


@pytest.mark.asyncio
async def test_ignores_soft_deleted_and_null_sections(seed_document_with_chunk):
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="viva", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(
        title="morta", kb_root_page_id=ROOT, kb_section="Fantasma", soft_deleted=True
    )
    await seed_document_with_chunk(title="sem", kb_root_page_id=ROOT, kb_section=None)

    assert await ListKnowledgeSectionsAction().execute() == ["Programs"]


@pytest.mark.asyncio
async def test_list_sections_includes_document_without_provenance(seed_document_with_chunk):
    """Desde o ADR-0015 não há guarda fail-closed amarrada à configuração de
    roots: documento sem `kb_root_page_id` gravado entra normalmente na lista
    de seções, como qualquer outro documento aprovado."""
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(
        title="Sem procedência", kb_root_page_id=None, kb_section="Fantasma"
    )

    assert await ListKnowledgeSectionsAction().execute() == ["Fantasma"]


@pytest.mark.asyncio
async def test_sections_differing_only_by_whitespace_collapse(seed_document_with_chunk):
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="c1", kb_root_page_id=ROOT, kb_section="Conferences ")
    await seed_document_with_chunk(title="c2", kb_root_page_id=ROOT, kb_section="Conferences")

    assert await ListKnowledgeSectionsAction().execute() == ["Conferences"]
