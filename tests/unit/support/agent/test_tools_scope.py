"""`fetch_notion_page` não pode furar a curadoria (ADR-0015): página que a
`KnowledgeCurationPolicy` reprova — linha de banco (PII), título na denylist —
não vira contexto de resposta, mesmo sendo legível pela integração."""

import pytest

from src.support.agent.tools import FetchNotionTool
from src.support.clients.notion.notion_client import NotionPage


class _FakeNotion:
    """Client falso: registra o que foi pedido e simula o veredito da curadoria."""

    def __init__(self, approved: bool) -> None:
        self._approved = approved
        self.fetched: list[str] = []

    async def get_page_with_provenance(self, page_id: str) -> NotionPage:
        self.fetched.append(page_id)
        return NotionPage(
            id=page_id,
            title="Bootcamp Web3",
            content="conteúdo da página",
            url="https://notion.so/p",
            is_approved=self._approved,
            kb_root_page_id="products",
        )


@pytest.mark.asyncio
async def test_approved_page_is_returned_as_tool_content():
    notion = _FakeNotion(approved=True)
    out = await FetchNotionTool(notion=notion).run("pagina-de-products")

    assert out.startswith("<<TOOL_CONTENT>>")
    assert "conteúdo da página" in out
    assert notion.fetched == ["pagina-de-products"]


@pytest.mark.asyncio
async def test_content_rejected_by_curation_never_reaches_the_model():
    # Regressão da Task 3: sem esta checagem, tirar a ancestralidade deixaria
    # linha de banco (PII) entrar direto no contexto da resposta.
    notion = _FakeNotion(approved=False)
    out = await FetchNotionTool(notion=notion).run("linha-de-tracker")

    assert "conteúdo da página" not in out
    assert "fora do escopo" in out.lower()
