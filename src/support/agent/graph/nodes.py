"""Nós do grafo do turno. Cada nó lê `deps` e `signals` do config — nada de
estado global, e os repositórios de dentro de `deps` carregam a sessão deste
request (regra 3)."""

import asyncio
import logging
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.support.agent.graph.state import TurnState
from src.support.agent.models import build_chat_model, build_small_model
from src.support.agent.prompts import SYSTEM_PROMPT
from src.support.agent.tools import build_tools, format_knowledge
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


async def retrieve_node(state: TurnState, config) -> dict:
    """RAG clássico: top-k no pgvector sobre a query que o gate reescreveu.

    Roda com a sessão de banco viva porque o runner dirige o grafo até aqui
    dentro do escopo do request — ver spec, seção 5. Falha aqui sobe: um turno
    sem contexto quando deveria ter é pior que um erro visível.
    """
    signals = config["configurable"]["signals"]
    deps = config["configurable"]["deps"]

    signals.retrieval_ran = True
    signals.retrieval_top_k = settings.RAG_TOP_K
    signals.retrieval_threshold = settings.RAG_MAX_DISTANCE

    started = time.monotonic()
    knowledge = await deps.search.execute(state["search_query"])
    signals.retrieval_ms = int((time.monotonic() - started) * 1000)
    signals.retrieval_kept = len(knowledge)
    return {"knowledge": knowledge}


async def refuse_node(state: TurnState, config) -> dict:
    """Recusa padrão: nada passou do limiar. Determinística, sem LLM."""
    signals = config["configurable"]["signals"]
    deps = config["configurable"]["deps"]

    signals.retrieval_best_distance = await _nearest_or_none(deps, state.get("search_query", ""))
    signals.outcome = "refusal"

    sections = await deps.sections.execute()
    return {
        "answer": deps.refusal(sections, state["question"]),
        "citations": [],
        "outcome": "refusal",
    }


async def _nearest_or_none(deps, query: str) -> float | None:
    """Só no caminho de recusa, e só para o trace. Falha aqui não pode custar a
    recusa ao usuário."""
    if deps.nearest is None or not query:
        return None
    try:
        return await deps.nearest.execute(query)
    except Exception:
        logger.warning("falha ao medir a distância do vizinho mais próximo", exc_info=True)
        return None


def _answer_messages(state: TurnState) -> list:
    """Mesmo prompt de sempre: histórico, contexto embrulhado, pergunta."""
    parts = [f"{m.role}: {m.content}" for m in state.get("history", [])]
    parts.append("Contexto recuperado da base de conhecimento:")
    parts.append(format_knowledge(state.get("knowledge", [])))
    parts.append(f"Pergunta do usuário: {state['question']}")
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content="\n\n".join(parts))]


def _answer_model(config, enable_tools: bool = True):
    injected = config.get("configurable", {}).get("answer_model")
    model = injected or build_chat_model()
    return model.bind_tools(build_tools()) if enable_tools else model


def _fill_usage(signals, message: AIMessage) -> None:
    """usage_metadata é o campo estável do LangChain, mas em streaming depende de
    flag por provider. Sem ele, o trace fica sem tokens — nunca derruba o turno."""
    try:
        usage = getattr(message, "usage_metadata", None) or {}
        if usage.get("input_tokens") is not None:
            signals.input_tokens = int(usage["input_tokens"])
        if usage.get("output_tokens") is not None:
            signals.output_tokens = int(usage["output_tokens"])
    except Exception:  # pragma: no cover - observabilidade não derruba turno
        logger.warning("não foi possível ler o usage do run", exc_info=True)


async def answer_node(state: TurnState, config) -> dict:
    """Resposta do oráculo. Os tokens saem daqui pelo stream_mode="messages" do
    LangGraph; este nó devolve a mensagem completa para o tool loop."""
    cfg = config["configurable"]
    signals = cfg["signals"]

    messages = state.get("messages") or _answer_messages(state)
    model = _answer_model(config, enable_tools=cfg.get("enable_tools", True))
    message = await model.ainvoke(messages)

    _fill_usage(signals, message)
    signals.outcome = "answer"

    kb = [s.citation for s in state.get("knowledge", [])]
    return {
        "messages": [message],
        "citations": kb + list(cfg.get("citations", [])),
        "outcome": "answer",
    }
