from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.support.clients.notion.notion_client import NotionPage


def test_approved_page_maps_to_approved_document():
    page = NotionPage(id="pid", title="T", content="C", url="https://n", is_approved=True)
    doc = NotionPageMapper.to_document(page, root_page_id="root")
    assert doc.notion_page_id == "pid"
    assert doc.status == "approved"
    assert doc.is_approved()


def test_unapproved_page_maps_to_pending():
    page = NotionPage(id="pid", title="T", content="C", url="https://n", is_approved=False)
    assert NotionPageMapper.to_document(page, root_page_id="root").status == "pending"
