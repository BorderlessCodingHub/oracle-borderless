"""Ferramentas do oráculo. Conteúdo de fonte SEMPRE entre <<TOOL_CONTENT>> (dado
não-confiável). web_search e fetch_notion_page são HTTP (não tocam o banco), então
rodam com segurança durante o streaming."""

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.clients.notion.notion_client import NotionClient
from src.support.clients.tavily.tavily_client import TavilyClient

_OPEN = "<<TOOL_CONTENT>>"
_CLOSE = "<</TOOL_CONTENT>>"


def wrap_tool_content(text: str) -> str:
    return f"{_OPEN}\n{text}\n{_CLOSE}"


def format_knowledge(snippets: list[KnowledgeSnippet]) -> str:
    if not snippets:
        return wrap_tool_content("(nenhum trecho relevante na base de conhecimento)")
    blocks = [
        f"[Fonte: {s.citation.title} — {s.citation.url}]\n{s.content}" for s in snippets
    ]
    return wrap_tool_content("\n\n".join(blocks))


class WebSearchTool:
    def __init__(self, tavily: TavilyClient, collected: list[Citation]) -> None:
        self._tavily = tavily
        self._collected = collected

    async def run(self, query: str) -> str:
        results = await self._tavily.search(query)
        for r in results:
            self._collected.append(
                Citation(source_type="web", title=r.title, url=r.url, snippet=r.content[:200])
            )
        body = "\n\n".join(f"[{r.title} — {r.url}]\n{r.content}" for r in results)
        return wrap_tool_content(body or "(sem resultados na web)")


class FetchNotionTool:
    """Busca uma página do Notion por id — **restrita ao escopo da KB** (ADR-0011).

    O id chega do modelo (via citação ou inferência), não da travessia de
    descoberta, então o escopo tem de ser checado aqui: sem isso a tool leria
    qualquer página do workspace visível à integração.
    """

    def __init__(self, notion: NotionClient) -> None:
        self._notion = notion

    async def run(self, page_id: str) -> str:
        page = await self._notion.get_page_in_scope(page_id)
        if page is None:
            return wrap_tool_content(
                "(página fora do escopo da base de conhecimento — não disponível)"
            )
        return wrap_tool_content(f"[{page.title} — {page.url}]\n{page.content}")
