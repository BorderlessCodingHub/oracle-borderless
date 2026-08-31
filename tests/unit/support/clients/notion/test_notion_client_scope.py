import pytest

from src.support.clients.notion.notion_client import (
    KnowledgeBaseConfigError,
    NotionClient,
)


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


def _fake_session(call):
    """Substitui `notion_mcp_session` por um contexto que devolve `call`."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session():
        yield call

    return session


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


@pytest.mark.asyncio
async def test_collect_scope_stamps_the_root_it_was_found_under():
    tree = {"rootA": [_child_page("A", "Programs")], "A": []}
    client = NotionClient()

    pages = await client._collect_scope(_make_call(tree, []), "rootA")

    assert [p.kb_root_page_id for p in pages] == ["roota"]


def _make_discovery_call(tree: dict[str, list[dict]], roots: list[dict], requested: list[str]):
    """`call` que atende tanto a busca de roots quanto a travessia de blocos."""

    async def call(tool: str, args: dict):
        if tool == "API-post-search":
            return {"results": roots, "has_more": False}
        assert tool == "API-get-block-children"
        block_id = args["block_id"]
        requested.append(block_id)
        return {"results": tree.get(block_id, []), "has_more": False}

    return call


def _workspace_page(page_id: str, title: str) -> dict:
    return {
        "object": "page",
        "id": page_id,
        "parent": {"type": "workspace"},
        "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}},
    }


@pytest.mark.asyncio
async def test_roots_come_from_what_the_integration_sees(monkeypatch):
    # Nenhuma env var: o escopo é o que o search devolve no nível do workspace.
    tree = {
        "roota": [_child_page("A", "Programs")],
        "A": [],
        "rootb": [_child_page("B", "Código de Cultura")],
        "B": [],
    }
    roots = [_workspace_page("roota", "Products"), _workspace_page("rootb", "Código de Cultura")]
    requested: list[str] = []
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, requested)),
    )

    pages = await NotionClient().list_approved_pages()

    assert {p.id for p in pages} == {"A", "B"}
    assert {p.id: p.kb_root_page_id for p in pages} == {"A": "roota", "B": "rootb"}


@pytest.mark.asyncio
async def test_a_page_below_a_root_that_was_never_in_any_allowlist_is_discovered(monkeypatch):
    # Regressão do critério de aceite: página de um root que nunca esteve na
    # allowlist entra sem nenhuma mudança de configuração.
    tree = {"labs": [_child_page("L1", "Coding Labs — guia")], "L1": []}
    roots = [_workspace_page("labs", "Borderless Coding Labs")]
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, [])),
    )

    pages = await NotionClient().list_approved_pages()

    assert [p.id for p in pages] == ["L1"]
    assert pages[0].kb_root_page_id == "labs"


@pytest.mark.asyncio
async def test_page_reachable_from_two_roots_keeps_the_first_discovered(monkeypatch):
    tree = {
        "roota": [_child_page("SHARED", "Compartilhada")],
        "rootb": [_child_page("SHARED", "Compartilhada")],
        "SHARED": [],
    }
    roots = [_workspace_page("roota", "Products"), _workspace_page("rootb", "Cultura")]
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, [])),
    )

    pages = await NotionClient().list_approved_pages()

    assert len(pages) == 1
    assert pages[0].kb_root_page_id == "roota"


@pytest.mark.asyncio
async def test_empty_discovery_aborts_instead_of_wiping_the_base(monkeypatch):
    # Descoberta vazia = token revogado / MCP fora do ar. Reconciliar isso
    # soft-deletaria toda a base numa rodada — por isso aborta.
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call({}, [], [])),
    )

    with pytest.raises(KnowledgeBaseConfigError):
        await NotionClient().list_approved_pages()


@pytest.mark.asyncio
async def test_a_root_with_a_denylisted_title_is_never_visited(monkeypatch):
    # Regressão do Achado 1: um root de nível de workspace cujo título bate a
    # denylist ("Sprints 2026") não pode ter a subárvore percorrida — mesmo
    # que o corpo do root em si nunca entre na lista de aprovados. Antes desta
    # checagem, cada filho do root entrava por conta própria em
    # `_collect_scope`, porque a poda por denylist só valia a partir dos
    # blocos visitados dentro da travessia, nunca no próprio root recebido.
    tree = {
        "sprints": [_child_page("S1", "Sprint 42")],
        "S1": [],
        "labs": [_child_page("L1", "Coding Labs — guia")],
        "L1": [],
    }
    roots = [
        _workspace_page("sprints", "Sprints 2026"),
        _workspace_page("labs", "Borderless Coding Labs"),
    ]
    requested: list[str] = []
    monkeypatch.setattr(
        "src.support.clients.notion.notion_client.notion_mcp_session",
        _fake_session(_make_discovery_call(tree, roots, requested)),
    )

    pages = await NotionClient().list_approved_pages()

    assert {p.id for p in pages} == {"L1"}
    assert "sprints" not in requested  # subárvore do root barrado não é visitada
    assert "S1" not in requested
