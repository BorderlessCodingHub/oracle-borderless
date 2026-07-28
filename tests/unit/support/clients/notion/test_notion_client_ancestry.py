"""Escopo por ancestralidade: `is_in_scope` responde se uma página está DENTRO da
subárvore do root configurado (ADR-0011). Usado para barrar acesso avulso a
páginas fora do escopo — a travessia de sync só cobre a descoberta."""

import pytest

from src.support.clients.notion.notion_client import (
    KnowledgeBaseConfigError,
    NotionClient,
)
from src.support.core.settings import settings

ROOT = "23d8d655-c889-806d-8828-d527ce6a1529"


def _page(page_id: str, parent: dict) -> dict:
    return {"object": "page", "id": page_id, "parent": parent}


def _make_call(pages: dict[str, dict]):
    async def call(tool: str, args: dict):
        assert tool == "API-retrieve-a-page"
        return pages[args["page_id"]]

    return call


@pytest.fixture(autouse=True)
def _root_configured(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", ROOT, raising=False)


@pytest.mark.asyncio
async def test_page_nested_under_root_is_in_scope():
    # ROOT → mid → leaf
    pages = {
        "leaf": _page("leaf", {"type": "page_id", "page_id": "mid"}),
        "mid": _page("mid", {"type": "page_id", "page_id": ROOT}),
        ROOT: _page(ROOT, {"type": "workspace", "workspace": True}),
    }
    assert await NotionClient()._is_in_scope(_make_call(pages), "leaf") is True


@pytest.mark.asyncio
async def test_the_root_itself_is_in_scope():
    pages = {ROOT: _page(ROOT, {"type": "workspace", "workspace": True})}
    assert await NotionClient()._is_in_scope(_make_call(pages), ROOT) is True


@pytest.mark.asyncio
async def test_page_under_another_top_level_folder_is_out_of_scope():
    # "Growth & Marketing" (irmão de Products, no nível do workspace) → sop
    other_root = "23d8d655-c889-81cb-aa18-c2a77019aa77"
    pages = {
        "sop": _page("sop", {"type": "page_id", "page_id": other_root}),
        other_root: _page(other_root, {"type": "workspace", "workspace": True}),
    }
    assert await NotionClient()._is_in_scope(_make_call(pages), "sop") is False


@pytest.mark.asyncio
async def test_database_row_is_out_of_scope():
    pages = {"row": _page("row", {"type": "database_id", "database_id": "db1"})}
    assert await NotionClient()._is_in_scope(_make_call(pages), "row") is False


@pytest.mark.asyncio
async def test_id_formatting_differences_do_not_break_the_match():
    """O MCP devolve UUID com hífens; ids vindos de citação podem vir sem."""
    undashed = ROOT.replace("-", "")
    pages = {
        "leaf": _page("leaf", {"type": "page_id", "page_id": undashed}),
        undashed: _page(undashed, {"type": "workspace", "workspace": True}),
    }
    assert await NotionClient()._is_in_scope(_make_call(pages), "leaf") is True


@pytest.mark.asyncio
async def test_cycle_does_not_hang():
    pages = {
        "a": _page("a", {"type": "page_id", "page_id": "b"}),
        "b": _page("b", {"type": "page_id", "page_id": "a"}),
    }
    assert await NotionClient()._is_in_scope(_make_call(pages), "a") is False


@pytest.mark.asyncio
async def test_get_page_in_scope_raises_without_root(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)
    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().get_page_in_scope("qualquer")
