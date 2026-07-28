"""Lista de temas que o oráculo cobre — alimenta a mensagem de recusa."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_lists_distinct_sections_sorted(monkeypatch, seed_document_with_chunk):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="d1", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(title="d2", kb_root_page_id=ROOT, kb_section="Bootcamps")
    await seed_document_with_chunk(title="d3", kb_root_page_id=ROOT, kb_section="Programs")

    assert await ListKnowledgeSectionsAction().execute() == ["Bootcamps", "Programs"]


@pytest.mark.asyncio
async def test_ignores_soft_deleted_and_null_sections(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="viva", kb_root_page_id=ROOT, kb_section="Programs")
    await seed_document_with_chunk(
        title="morta", kb_root_page_id=ROOT, kb_section="Fantasma", soft_deleted=True
    )
    await seed_document_with_chunk(title="sem", kb_root_page_id=ROOT, kb_section=None)

    assert await ListKnowledgeSectionsAction().execute() == ["Programs"]
