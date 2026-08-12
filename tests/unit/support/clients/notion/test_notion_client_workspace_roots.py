"""`list_workspace_root_pages` pagina a busca por páginas de nível workspace.
Cobre a combinação de páginas entre lotes, o repasse do cursor, e a guarda
contra `has_more=True` sem `next_cursor` (que travaria o `while True`)."""

from contextlib import asynccontextmanager

import pytest

from src.support.clients.notion.notion_client import NotionClient


def _workspace_page(page_id: str, title: str) -> dict:
    return {
        "object": "page",
        "id": page_id,
        "parent": {"type": "workspace"},
        "properties": {"title": {"type": "title", "title": [{"plain_text": title}]}},
    }


def _fake_session(call):
    @asynccontextmanager
    async def session():
        yield call

    return session


@pytest.mark.asyncio
async def test_combines_results_across_pages_and_forwards_the_cursor(monkeypatch):
    responses = {
        None: {
            "results": [_workspace_page("a", "Products")],
            "has_more": True,
            "next_cursor": "cursor-2",
        },
        "cursor-2": {
            "results": [_workspace_page("b", "Culture")],
            "has_more": False,
        },
    }
    requested_cursors: list[str | None] = []

    async def call(tool: str, args: dict):
        assert tool == "API-post-search"
        cursor = args.get("start_cursor")
        requested_cursors.append(cursor)
        return responses[cursor]

    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(call),
    )

    pages = await NotionClient().list_workspace_root_pages()

    assert {p.id for p in pages} == {"a", "b"}
    assert requested_cursors == [None, "cursor-2"]


@pytest.mark.asyncio
async def test_stops_when_has_more_is_true_without_a_next_cursor(monkeypatch):
    # `has_more=True` com `next_cursor` nulo faria `cursor` voltar a `None` e
    # o `while True` repetir a mesma chamada para sempre — a guarda precisa
    # tratar isso como fim da paginação, não como "continue".
    async def call(tool: str, args: dict):
        assert tool == "API-post-search"
        return {"results": [_workspace_page("a", "Products")], "has_more": True, "next_cursor": None}

    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(call),
    )

    pages = await NotionClient().list_workspace_root_pages()

    assert {p.id for p in pages} == {"a"}
