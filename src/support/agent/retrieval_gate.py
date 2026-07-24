"""Retrieval gate sobre Pydantic AI (ADR-0007): decide, com um modelo PEQUENO,
se o turno precisa da base de conhecimento e, em caso positivo, devolve uma query
de busca autônoma (contexto da conversa resolvido). Fail-open: qualquer erro
recupera a pergunta crua. Segundo (e único outro) lugar que importa pydantic_ai."""

import asyncio
import logging

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from src.support.agent.ports import AgentMessage, RetrievalDecision
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

GATE_SYSTEM_PROMPT = """\
Você é um roteador para a base de conhecimento do Oracle Borderless (documentos
curados do Notion: SOPs, processos de negócio, editoriais, dados operacionais).
Decida se responder à ÚLTIMA mensagem do usuário exige buscar nessa base.

- retrieve=false para: saudações, agradecimentos, conversa fiada, perguntas sobre
  você mesmo, e qualquer coisa totalmente respondível pelo histórico da conversa.
- retrieve=true para qualquer pergunta substantiva sobre o ecossistema, suas regras
  ou dados operacionais.

Quando retrieve=true, devolva também search_query: uma query AUTÔNOMA, no idioma da
pergunta, resolvendo pronomes/elipses a partir da conversa (ex.: "e as renovações?"
-> "renovação de PSP"). Quando retrieve=false, search_query é "".
"""


def _build_small_model():
    if settings.LLM_PROVIDER == "openai":
        return OpenAIChatModel(
            settings.OPENAI_SMALL_MODEL,
            provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY),
        )
    return AnthropicModel(
        settings.ANTHROPIC_SMALL_MODEL,
        provider=AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY),
    )


def _build_gate_agent() -> Agent:
    return Agent(
        _build_small_model(),
        system_prompt=GATE_SYSTEM_PROMPT,
        output_type=RetrievalDecision,
    )


def _build_prompt(question: str, history: list[AgentMessage]) -> str:
    parts = [f"{m.role}: {m.content}" for m in history]
    parts.append(f"Mensagem atual do usuário: {question}")
    return "\n\n".join(parts)


class RetrievalGate:
    def __init__(self, agent=None) -> None:
        self._agent = agent or _build_gate_agent()

    async def decide(
        self, question: str, history: list[AgentMessage]
    ) -> RetrievalDecision:
        prompt = _build_prompt(question, history)
        try:
            result = await asyncio.wait_for(
                self._agent.run(prompt), timeout=settings.GATE_TIMEOUT_SECONDS
            )
            decision = result.output
            if decision.retrieve and not decision.search_query.strip():
                return RetrievalDecision(retrieve=True, search_query=question)
            return decision
        except Exception:  # fail-open: uma recuperação a mais > uma perdida
            logger.warning("retrieval gate falhou; fail-open (query crua)", exc_info=True)
            return RetrievalDecision(retrieve=True, search_query=question)


def get_retrieval_gate() -> "RetrievalGate":
    return RetrievalGate()
