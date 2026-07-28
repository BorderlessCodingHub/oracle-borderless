import pytest

from src.support.clients.notion.notion_client import (
    KnowledgeBaseConfigError,
    NotionClient,
)
from src.support.core.settings import settings


def _child_page(bid: str, title: str) -> dict:
    return {
        "object": "block",
        "id": bid,
        "type": "child_page",
        "child_page": {"title": title},
        "last_edited_time": "2026-07-01T00:00:00.000Z",
    }


def _child_database(bid: str) -> dict:
    return {
        "object": "block",
        "id": bid,
        "type": "child_database",
        "child_database": {"title": "Onboarding Control"},
    }


def _paragraph(bid: str) -> dict:
    return {"object": "block", "id": bid, "type": "paragraph", "paragraph": {"rich_text": []}}


def _make_call(tree: dict[str, list[dict]], requested: list[str]):
    async def call(tool: str, args: dict):
        assert tool == "API-get-block-children"
        block_id = args["block_id"]
        requested.append(block_id)
        return {"results": tree.get(block_id, []), "has_more": False}

    return call


@pytest.mark.asyncio
async def test_collect_scope_returns_only_descendant_pages():
    # root → [A (ok), Backlog (denylist), DB (banco)] ; A → [A1 (ok)]
    tree = {
        "root": [_child_page("A", "Programs"), _child_page("BL", "Backlog Platform"), _child_database("DB")],
        "A": [_child_page("A1", "Bootcamp 2026"), _paragraph("p1")],
        "A1": [],
        "BL": [_child_page("BLX", "linha de backlog")],  # não deve ser visitado
    }
    requested: list[str] = []
    client = NotionClient()

    pages = await client._collect_scope(_make_call(tree, requested), "root")

    ids = {p.id for p in pages}
    assert ids == {"A", "A1"}                    # Backlog (denylist) e DB (banco) fora
    assert all(p.is_approved for p in pages)
    assert "BL" not in requested                 # subárvore de página rejeitada não é descida
    assert "DB" not in requested                 # child_database nunca é descido


@pytest.mark.asyncio
async def test_list_approved_pages_raises_when_root_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)
    client = NotionClient()

    with pytest.raises(KnowledgeBaseConfigError):
        await client.list_approved_pages()


@pytest.mark.asyncio
async def test_collect_scope_propagates_section_from_first_level():
    # root → [Bootcamps, Programs] ; Bootcamps → [Web3] ; Web3 → [Edição 02]
    tree = {
        "root": [_child_page("BC", "Bootcamps"), _child_page("PR", "Programs")],
        "BC": [_child_page("W3", "Web3 Global Developer")],
        "W3": [_child_page("E2", "Edição #02")],
        "PR": [],
        "E2": [],
    }
    pages = await NotionClient()._collect_scope(_make_call(tree, []), "root")
    section_by_id = {p.id: p.section for p in pages}

    assert section_by_id["BC"] == "Bootcamps"   # filho direto: seção é ele mesmo
    assert section_by_id["PR"] == "Programs"
    assert section_by_id["W3"] == "Bootcamps"   # neto herda
    assert section_by_id["E2"] == "Bootcamps"   # bisneto herda


@pytest.mark.asyncio
async def test_collect_scope_strips_section_title():
    tree = {"root": [_child_page("CF", "Conferences ")], "CF": []}
    pages = await NotionClient()._collect_scope(_make_call(tree, []), "root")
    assert pages[0].section == "Conferences"
