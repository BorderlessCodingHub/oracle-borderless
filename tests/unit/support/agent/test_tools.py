import pytest

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.navigation_catalog import NavigationCatalog
from src.support.agent.ports import KnowledgeSnippet
from src.support.agent.tools import (
    NAVIGATE_TOOL_NAME,
    WebSearchTool,
    build_tools,
    format_knowledge,
    tool_node_tools,
    wrap_tool_content,
)
from tests.fakes.fake_tavily_client import FakeTavilyClient


def test_wrap_tool_content_uses_markers():
    out = wrap_tool_content("abc")
    assert out.startswith("<<TOOL_CONTENT>>") and out.endswith("<</TOOL_CONTENT>>")


def test_format_knowledge_labels_sources():
    snips = [KnowledgeSnippet("trecho", Citation("notion", "Regras", "u", "s", "pid"))]
    text = format_knowledge(snips)
    assert "Regras" in text and "trecho" in text
    assert text.startswith("<<TOOL_CONTENT>>")


@pytest.mark.asyncio
async def test_web_search_tool_collects_citations():
    from src.support.clients.tavily.tavily_client import WebResult

    collected: list[Citation] = []
    fake = FakeTavilyClient(results=[WebResult(title="Artigo", url="https://ex/a", content="corpo")])
    tool = WebSearchTool(tavily=fake, collected=collected)
    out = await tool.run("pergunta pública")
    assert out.startswith("<<TOOL_CONTENT>>")
    assert "Artigo" in out
    assert len(collected) == 1
    assert all(c.source_type == "web" for c in collected)


# --- declaração das tools ------------------------------------------------


def test_build_tools_declares_the_three_tools_of_the_turn():
    assert [t.name for t in build_tools()] == ["web_search", "fetch_notion_page", NAVIGATE_TOOL_NAME]


def test_the_navigate_tool_carries_the_catalog_it_received_and_the_three_args():
    """O catálogo é o que ensina o modelo a escolher um id — ele vive na
    descrição da tool, não no system prompt."""
    navigate = build_tools("- code_breakers (activity): desafios de código")[-1]

    assert "- code_breakers (activity): desafios de código" in navigate.description
    assert set(navigate.args) == {"destination", "topic", "goal"}
    assert navigate.args["destination"]["type"] == "string"


def test_without_a_catalog_the_navigate_tool_falls_back_to_the_embedded_snapshot():
    """Sem token (ou com a API fora) a tool ainda descreve destinos válidos."""
    navigate = build_tools()[-1]

    assert NavigationCatalog.snapshot_text() in navigate.description


def test_tool_node_tools_excludes_navigate_platform():
    """`navigate_platform` é executada pelo nó `navigate`, nunca pelo ToolNode —
    o corpo da declaração é um RuntimeError de propósito."""
    assert [t.name for t in tool_node_tools()] == ["web_search", "fetch_notion_page"]
    assert NAVIGATE_TOOL_NAME not in [t.name for t in tool_node_tools()]
