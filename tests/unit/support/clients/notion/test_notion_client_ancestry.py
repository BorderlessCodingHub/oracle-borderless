"""Procedência por ancestralidade: `_find_top_level_page` responde de qual página
de topo uma página descende, subindo a cadeia de `parent` (ADR-0015). Não
autoriza nada — quem recusa é a curadoria."""

import pytest

from src.support.clients.notion.notion_client import NotionClient


def _make_call(pages: dict[str, dict]):
    async def call(tool: str, args: dict):
        assert tool == "API-retrieve-a-page"
        return pages[args["page_id"]]

    return call


@pytest.mark.asyncio
async def test_climbs_to_the_top_level_page():
    pages = {
        "leaf": {"parent": {"type": "page_id", "page_id": "mid"}},
        "mid": {"parent": {"type": "page_id", "page_id": "rootB"}},
        "rootB": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "leaf") == "rootb"


@pytest.mark.asyncio
async def test_a_top_level_page_is_its_own_provenance():
    pages = {"rootA": {"parent": {"type": "workspace"}}}
    assert await NotionClient()._find_top_level_page(_make_call(pages), "rootA") == "roota"


@pytest.mark.asyncio
async def test_any_top_level_page_qualifies_now():
    # "growth" nunca esteve em allowlist nenhuma; ainda assim é procedência
    # válida — não existe mais lista contra a qual comparar.
    pages = {
        "sop": {"parent": {"type": "page_id", "page_id": "growth"}},
        "growth": {"parent": {"type": "workspace"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "sop") == "growth"


@pytest.mark.asyncio
async def test_database_row_has_no_top_level_page():
    # Linha de banco não descende de página de topo. Procedência `None` — a
    # recusa em si é da curadoria, não daqui.
    pages = {"row": {"parent": {"type": "data_source_id", "data_source_id": "ds1"}}}
    assert await NotionClient()._find_top_level_page(_make_call(pages), "row") is None


@pytest.mark.asyncio
async def test_cycle_does_not_hang():
    pages = {
        "a": {"parent": {"type": "page_id", "page_id": "b"}},
        "b": {"parent": {"type": "page_id", "page_id": "a"}},
    }
    assert await NotionClient()._find_top_level_page(_make_call(pages), "a") is None


@pytest.mark.asyncio
async def test_get_page_with_provenance_stamps_the_top_level_page_it_descends_from(monkeypatch):
    """`kb_root_page_id=provenance` (o retorno de `_find_top_level_page`) é a
    única linha do caminho real sem cobertura direta: os fakes de
    `test_tools_scope.py`/`test_knowledge_ingest_command.py` substituem o
    client inteiro e não exercitam esta fiação. Se ela se perder, o comando
    `knowledge:ingest` grava `""` -> `None` de procedência, e a página fica
    invisível à recuperação, removida em silêncio no próximo sync full."""
    from contextlib import asynccontextmanager

    pages = {
        "leaf": {
            "parent": {"type": "page_id", "page_id": "mid"},
            "properties": {"title": {"type": "title", "title": [{"plain_text": "Leaf Page"}]}},
            "url": "https://notion.so/leaf",
        },
        "mid": {"parent": {"type": "page_id", "page_id": "rootA"}},
        "rootA": {"parent": {"type": "workspace"}},
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

    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        lambda: fake_session(),
    )

    page = await NotionClient().get_page_with_provenance("leaf")

    assert page is not None
    assert page.kb_root_page_id == "roota"
    assert page.title == "Leaf Page"
    assert page.is_approved is True
