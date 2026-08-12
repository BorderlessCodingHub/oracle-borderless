"""Lista de temas que o oráculo cobre — alimenta a mensagem de recusa."""

import pytest

from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


@pytest.mark.asyncio
async def test_lists_distinct_sections_sorted(monkeypatch, seed_document_with_chunk):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
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
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
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
async def test_list_sections_returns_empty_when_root_unconfigured(
    monkeypatch, seed_document_with_chunk
):
    """Sem root configurado, a lista de seções degrada para vazia.

    `DocumentModel.kb_root_page_id == None` compilaria para `IS NULL`, que
    combina exatamente com os documentos sem procedência — o guard-clause em
    `list_sections` existe para que a ausência de configuração nunca vire um
    "libera tudo sem procedência" por acidente.
    """
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(
        title="Sem procedência", kb_root_page_id=None, kb_section="Fantasma"
    )

    assert await ListKnowledgeSectionsAction().execute() == []


@pytest.mark.asyncio
async def test_sections_differing_only_by_whitespace_collapse(
    monkeypatch, seed_document_with_chunk
):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", ROOT, raising=False)
    from src.domain.documents.actions.list_knowledge_sections_action import (
        ListKnowledgeSectionsAction,
    )

    await seed_document_with_chunk(title="c1", kb_root_page_id=ROOT, kb_section="Conferences ")
    await seed_document_with_chunk(title="c2", kb_root_page_id=ROOT, kb_section="Conferences")

    assert await ListKnowledgeSectionsAction().execute() == ["Conferences"]
