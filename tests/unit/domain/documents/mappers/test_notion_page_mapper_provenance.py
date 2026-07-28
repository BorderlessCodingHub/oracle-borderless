from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.support.clients.notion.notion_client import NotionPage

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


def _page(**over) -> NotionPage:
    base = dict(
        id="p1",
        title="Web3 Bootcamp",
        content="conteúdo",
        url="https://notion.so/p1",
        is_approved=True,
        section="Bootcamps",
    )
    base.update(over)
    return NotionPage(**base)


def test_maps_section_and_normalized_root():
    doc = NotionPageMapper.to_document(_page(), root_page_id=ROOT)
    assert doc.kb_section == "Bootcamps"
    assert doc.kb_root_page_id == "23d8d655c889806d8828d527ce6a1529"  # sem hífens


def test_missing_section_maps_to_none():
    doc = NotionPageMapper.to_document(_page(section=None), root_page_id=ROOT)
    assert doc.kb_section is None
