"""`fetch_notion_page` não pode furar o escopo da KB (ADR-0011): página fora da
subárvore do root não vira contexto de resposta."""

import pytest

from src.support.agent.tools import FetchNotionTool
from src.support.clients.notion.notion_client import NotionPage


class _FakeNotion:
    """Client falso: registra o que foi pedido e simula o veredito de escopo."""

    def __init__(self, in_scope: bool) -> None:
        self._in_scope = in_scope
        self.fetched: list[str] = []

    async def get_page_with_provenance(self, page_id: str) -> NotionPage | None:
        self.fetched.append(page_id)
        if not self._in_scope:
            return None
        return NotionPage(
            id=page_id,
            title="Bootcamp Web3",
            content="conteúdo da página",
            url="https://notion.so/p",
            is_approved=True,
        )


@pytest.mark.asyncio
async def test_in_scope_page_is_returned_as_tool_content():
    notion = _FakeNotion(in_scope=True)
    out = await FetchNotionTool(notion=notion).run("pagina-de-products")

    assert out.startswith("<<TOOL_CONTENT>>")
    assert "conteúdo da página" in out
    assert notion.fetched == ["pagina-de-products"]


@pytest.mark.asyncio
async def test_out_of_scope_page_content_never_reaches_the_model():
    notion = _FakeNotion(in_scope=False)
    out = await FetchNotionTool(notion=notion).run("sop-fora-do-escopo")

    assert "conteúdo da página" not in out
    assert "fora do escopo" in out.lower()
