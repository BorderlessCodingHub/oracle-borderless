"""Nós do grafo do turno. Cada nó lê `deps` e `signals` do config — nada de
estado global, e os repositórios de dentro de `deps` carregam a sessão deste
request (regra 3)."""

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from src.support.agent.graph.state import TurnState
from src.support.agent.models import build_small_model
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


class _GateOutput(BaseModel):
    """Saída estruturada do gate. Pydantic porque é o que
    `with_structured_output` aceita; o tipo público continua sendo
    `RetrievalDecision` em ports.py."""

    retrieve: bool = Field(description="true se a pergunta exige buscar na base")
    search_query: str = Field(default="", description="query autônoma, ou '' quando retrieve=false")


def _gate_prompt(state: TurnState) -> list[dict]:
    parts = [f"{m.role}: {m.content}" for m in state.get("history", [])]
    parts.append(f"Mensagem atual do usuário: {state['question']}")
    return [
        {"role": "system", "content": GATE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _gate_model(config):
    """Permite injetar um fake nos testes sem tocar em build_small_model."""
    injected = config.get("configurable", {}).get("gate_model")
    return injected or build_small_model().with_structured_output(_GateOutput)


async def gate_node(state: TurnState, config) -> dict:
    """Decide se o turno precisa da base e reescreve a query. Fail-open."""
    signals = config["configurable"]["signals"]
    question = state["question"]
    started = time.monotonic()
    try:
        model = _gate_model(config)
        out = await asyncio.wait_for(
            model.ainvoke(_gate_prompt(state)), timeout=settings.GATE_TIMEOUT_SECONDS
        )
        query = out.search_query.strip() or question if out.retrieve else ""
        result = {"retrieve": out.retrieve, "search_query": query, "degraded": False}
    except Exception:
        # fail-open: uma recuperação a mais > uma perdida. degraded=True avisa a
        # aresta has_grounding de que NÃO houve classificação — só um chute.
        logger.warning("retrieval gate falhou; fail-open (query crua)", exc_info=True)
        result = {"retrieve": True, "search_query": question, "degraded": True}

    signals.gate_ms = int((time.monotonic() - started) * 1000)
    signals.gate_retrieve = result["retrieve"]
    signals.gate_search_query = result["search_query"] or None
    signals.gate_degraded = result["degraded"]
    return result
