"""Ferramentas do oráculo. Conteúdo de fonte SEMPRE entre <<TOOL_CONTENT>> (dado
não-confiável). web_search e fetch_notion_page são HTTP (não tocam o banco), então
rodam com segurança durante o streaming."""

import logging

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.clients.notion.notion_client import NotionClient
from src.support.clients.tavily.tavily_client import TavilyClient

logger = logging.getLogger(__name__)

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
    """Busca uma página do Notion por id — **filtrada pela curadoria** (ADR-0015).

    O id chega do modelo (via citação ou inferência), não da travessia de
    descoberta. O escopo em si é a permissão da integração, que o MCP já aplica;
    o que precisa ser checado aqui é o veredito da `KnowledgeCurationPolicy`,
    que barra linha de banco (tracker/PII) e títulos da denylist.
    """

    def __init__(self, notion: NotionClient) -> None:
        self._notion = notion

    async def run(self, page_id: str) -> str:
        page = await self._notion.get_page_with_provenance(page_id)
        if not page.is_approved:
            return wrap_tool_content(
                "(página fora do escopo da base de conhecimento — não disponível)"
            )
        return wrap_tool_content(f"[{page.title} — {page.url}]\n{page.content}")


def build_tools() -> list:
    """As duas tools no formato LangChain.

    O `config` é injetado pelo runtime — o modelo não o vê. É por ele que vêm o
    coletor de citações e o `signals` deste turno; nada de estado global.
    """
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import tool

    @tool
    async def web_search(query: str, config: RunnableConfig) -> str:
        """Busca informação pública na web. NÃO é fallback para lacunas da base
        interna — quando o contexto fornecido não cobre a pergunta, a resposta é
        a recusa padrão, não uma busca web."""
        cfg = config["configurable"]
        cfg["signals"].tool_calls += 1
        try:
            return await WebSearchTool(tavily=TavilyClient(), collected=cfg["citations"]).run(query)
        except Exception as exc:  # falha de tool não derruba o streaming
            logger.exception("web_search tool failed")
            return wrap_tool_content(f"(falha ao buscar na web: {exc})")

    @tool
    async def fetch_notion_page(page_id: str, config: RunnableConfig) -> str:
        """Busca o conteúdo completo/atualizado de uma página do Notion."""
        config["configurable"]["signals"].tool_calls += 1
        try:
            return await FetchNotionTool(notion=NotionClient()).run(page_id)
        except Exception as exc:  # falha de tool não derruba o streaming
            logger.exception("fetch_notion_page tool failed")
            return wrap_tool_content(f"(falha ao buscar página do Notion: {exc})")

    return [web_search, fetch_notion_page]
