"""Motor real do oráculo sobre Pydantic AI (ADR-0007). Único lugar que importa
pydantic_ai. RAG clássico (knowledge injetado) + tools HTTP agênticas."""

import logging
from typing import AsyncIterator

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, AgentStreamChunk, KnowledgeSnippet, TurnMetrics
from src.support.agent.prompts import SYSTEM_PROMPT
from src.support.agent.tools import FetchNotionTool, WebSearchTool, format_knowledge, wrap_tool_content
from src.support.clients.notion.notion_client import NotionClient
from src.support.clients.tavily.tavily_client import TavilyClient
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


def _build_model():
    """Modelo pydantic-ai com a chave vinda de settings (não do ambiente).

    O provider do pydantic-ai leria a API key de `os.environ`; como as chaves
    vivem no `.env`/settings (não exportadas), injetamos explícito — igual ao
    OpenAIEmbeddingsClient.
    """
    if settings.LLM_PROVIDER == "openai":
        return OpenAIChatModel(
            settings.OPENAI_MODEL,
            provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY),
        )
    return AnthropicModel(
        settings.ANTHROPIC_MODEL,
        provider=AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY),
    )


def _build_prompt(question: str, history: list[AgentMessage], knowledge: list[KnowledgeSnippet]) -> str:
    parts: list[str] = []
    for msg in history:
        parts.append(f"{msg.role}: {msg.content}")
    parts.append("Contexto recuperado da base de conhecimento:")
    parts.append(format_knowledge(knowledge))
    parts.append(f"Pergunta do usuário: {question}")
    return "\n\n".join(parts)


class OracleEngine:
    def __init__(self, model=None, enable_tools: bool = True) -> None:
        self._model = model or _build_model()
        self._enable_tools = enable_tools

    async def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet],
        metrics: TurnMetrics | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
        web_citations: list[Citation] = []

        agent = Agent(self._model, system_prompt=SYSTEM_PROMPT)

        if self._enable_tools:
            web_tool = WebSearchTool(tavily=TavilyClient(), collected=web_citations)
            notion_tool = FetchNotionTool(notion=NotionClient())

            @agent.tool_plain
            async def web_search(query: str) -> str:
                """Busca informação pública na web. NÃO é fallback para lacunas da
                base interna — quando o contexto fornecido não cobre a pergunta, a
                resposta é a recusa padrão, não uma busca web."""
                try:
                    return await web_tool.run(query)
                except Exception as exc:  # falha de tool não deve derrubar o streaming
                    logger.exception("web_search tool failed")
                    return wrap_tool_content(f"(falha ao buscar na web: {exc})")

            @agent.tool_plain
            async def fetch_notion_page(page_id: str) -> str:
                """Busca o conteúdo completo/atualizado de uma página do Notion."""
                try:
                    return await notion_tool.run(page_id)
                except Exception as exc:  # falha de tool não deve derrubar o streaming
                    logger.exception("fetch_notion_page tool failed")
                    return wrap_tool_content(f"(falha ao buscar página do Notion: {exc})")

        prompt = _build_prompt(question, history, knowledge)
        async with agent.run_stream(prompt) as result:
            async for delta in result.stream_text(delta=True):
                yield AgentStreamChunk(type="text", text=delta)

        kb_citations = [s.citation for s in knowledge]
        yield AgentStreamChunk(type="sources", citations=kb_citations + web_citations)


def get_oracle_engine(enable_tools: bool = True) -> "OracleEngine":
    return OracleEngine(enable_tools=enable_tools)
