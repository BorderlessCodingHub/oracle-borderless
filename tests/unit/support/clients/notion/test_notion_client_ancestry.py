"""Escopo por ancestralidade: `_find_root` responde QUAL root (dos vários
configurados) contém uma página, subindo a cadeia de `parent` (ADR-0012).
Usado para barrar acesso avulso a páginas fora de todo root — a travessia de
sync só cobre a descoberta."""

import pytest

from src.support.clients.notion.notion_client import KnowledgeBaseConfigError, NotionClient
from src.support.core.settings import settings


def _page(page_id: str, parent: dict) -> dict:
    return {"object": "page", "id": page_id, "parent": parent}


def _make_call(pages: dict[str, dict]):
    async def call(tool: str, args: dict):
        assert tool == "API-retrieve-a-page"
        return pages[args["page_id"]]

    return call


ROOTS = ("roota", "rootb")


@pytest.mark.asyncio
async def test_find_root_returns_the_matching_root_for_a_nested_page():
    pages = {
        "leaf": {"parent": {"type": "page_id", "page_id": "mid"}},
        "mid": {"parent": {"type": "page_id", "page_id": "rootB"}},
        "rootB": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "leaf", ROOTS) == "rootb"


@pytest.mark.asyncio
async def test_find_root_returns_the_root_itself():
    pages = {"rootA": {"parent": {"type": "workspace"}}}
    assert await NotionClient()._find_root(_make_call(pages), "rootA", ROOTS) == "roota"


@pytest.mark.asyncio
async def test_find_root_returns_none_for_a_sibling_outside_every_root():
    pages = {
        "sop": {"parent": {"type": "page_id", "page_id": "growth"}},
        "growth": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "sop", ROOTS) is None


@pytest.mark.asyncio
async def test_find_root_returns_none_for_a_database_row():
    pages = {"row": {"parent": {"type": "database_id", "database_id": "db"}}}
    assert await NotionClient()._find_root(_make_call(pages), "row", ROOTS) is None


@pytest.mark.asyncio
async def test_find_root_survives_a_parent_cycle():
    pages = {
        "a": {"parent": {"type": "page_id", "page_id": "b"}},
        "b": {"parent": {"type": "page_id", "page_id": "a"}},
    }
    assert await NotionClient()._find_root(_make_call(pages), "a", ROOTS) is None


@pytest.mark.asyncio
async def test_get_page_in_scope_raises_without_roots(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)

    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().get_page_in_scope("qualquer")


@pytest.mark.asyncio
async def test_get_page_in_scope_stamps_the_root_that_matched(monkeypatch):
    """`kb_root_page_id=matched_root` (o retorno de `_find_root`) é a única linha
    nova do caminho de escopo sem cobertura direta. Se ela se perder, o comando
    `knowledge:ingest` grava `""` -> `None` de procedência, e a página fica
    invisível à recuperação, removida em silêncio no próximo sync full."""
    from contextlib import asynccontextmanager

    pages = {
        "leaf": {
            "parent": {"type": "page_id", "page_id": "roota"},
            "properties": {"title": {"type": "title", "title": [{"plain_text": "Leaf Page"}]}},
            "url": "https://notion.so/leaf",
        },
    }

    async def call(tool: str, args: dict):
        if tool == "API-retrieve-a-page":
            return pages[args["page_id"]]
        if tool == "API-retrieve-page-markdown":
            return {"markdown": "conteúdo", "truncated": False}
        raise AssertionError(f"tool inesperada: {tool}")

    @asynccontextmanager
    async def fake_session():
        yield call

    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "rootA,rootB", raising=False)
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        lambda: fake_session(),
    )

    page = await NotionClient().get_page_in_scope("leaf")

    assert page is not None
    assert page.kb_root_page_id == "roota"
    assert page.title == "Leaf Page"
