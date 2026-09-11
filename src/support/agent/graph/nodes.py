"""Nós do grafo do turno. Cada nó lê `deps` e `signals` do config — nada de
estado global, e os repositórios de dentro de `deps` carregam a sessão deste
request (regra 3)."""

import asyncio
import logging
import time
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.support.agent.graph.state import TurnState
from src.support.agent.models import build_chat_model, build_small_model
from src.support.agent.prompts import build_system_prompt
from src.support.agent.tools import build_mentor_tools, format_knowledge, model_bound_tools
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

GATE_SYSTEM_PROMPT = """\
Você é um roteador para a base de conhecimento do Oracle Borderless (documentos
curados do Notion: SOPs, processos de negócio, editoriais, dados operacionais).
Decida se responder à ÚLTIMA mensagem do usuário exige buscar nessa base.

Classifique também `intent`:
- navigate: o usuário quer IR a algum lugar da plataforma, ENCONTRAR um conteúdo
  ou COMEÇAR uma atividade (ex.: "quero praticar algoritmos", "me leva para as
  trilhas de backend", "onde vejo meus eventos?", "quero treinar system design").
  Para navigate, retrieve=false e search_query="".
- chit_chat: saudações, agradecimentos, conversa fiada, perguntas sobre você.
- knowledge: qualquer pergunta substantiva sobre o ecossistema, suas regras ou dados.

- retrieve=false para: saudações, agradecimentos, conversa fiada, perguntas sobre
  você mesmo, e qualquer coisa totalmente respondível pelo histórico da conversa.
  Uma resposta anterior dizendo que NÃO encontrou informações não torna a pergunta
  respondível pelo histórico — se o usuário insiste ou reformula, retrieve=true.
- retrieve=true para qualquer pergunta substantiva sobre o ecossistema, suas regras
  ou dados operacionais.

Quando retrieve=true, devolva também search_query: a pergunta reescrita de forma
AUTÔNOMA, no idioma da pergunta, resolvendo pronomes/elipses a partir da conversa.
Mantenha a forma de pergunta completa — NÃO condense em palavras-chave (ex.:
"e as renovações?" -> "como funciona a renovação da mentoria PSP?", nunca
"renovação PSP"). Se a pergunta já é autônoma, devolva-a como está.
Quando retrieve=false, search_query é "".
"""


class _GateOutput(BaseModel):
    """Saída estruturada do gate. Pydantic porque é o que
    `with_structured_output` aceita; o tipo público continua sendo
    `RetrievalDecision` em ports.py."""

    retrieve: bool = Field(description="true se a pergunta exige buscar na base")
    search_query: str = Field(default="", description="query autônoma, ou '' quando retrieve=false")
    intent: Literal["knowledge", "navigate", "chit_chat"] = Field(
        default="knowledge",
        description=(
            "knowledge=pergunta sobre a base; navigate=quer ir a um lugar/começar "
            "uma atividade na plataforma; chit_chat=saudação/conversa"
        ),
    )


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
        # navigate nunca retrieva, mesmo se o modelo devolveu retrieve=True junto:
        # a classificação de intent tem prioridade sobre o campo retrieve solto.
        retrieve = out.retrieve and out.intent == "knowledge"
        query = out.search_query.strip() or question if retrieve else ""
        result = {"retrieve": retrieve, "search_query": query, "degraded": False, "intent": out.intent}
    except Exception:
        # fail-open: uma recuperação a mais > uma perdida. degraded=True avisa a
        # aresta has_grounding de que NÃO houve classificação — só um chute.
        logger.warning("retrieval gate falhou; fail-open (query crua)", exc_info=True)
        result = {"retrieve": True, "search_query": question, "degraded": True, "intent": "knowledge"}

    signals.gate_ms = int((time.monotonic() - started) * 1000)
    signals.gate_retrieve = result["retrieve"]
    signals.gate_search_query = result["search_query"] or None
    signals.gate_degraded = result["degraded"]
    signals.intent = result["intent"]
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
    query = state["search_query"]
    knowledge = await deps.search.execute(query)
    if not knowledge and state.get("question") and query != state["question"]:
        # A reescrita do gate pode condensar a pergunta em palavras-chave que
        # embedam pior que o texto original e caem fora do limiar. Antes de
        # recusar, tenta a pergunta crua — uma recuperação a mais > uma perdida.
        query = state["question"]
        knowledge = await deps.search.execute(query)
    signals.retrieval_ms = int((time.monotonic() - started) * 1000)
    signals.retrieval_kept = len(knowledge)
    return {"knowledge": knowledge, "search_query": query}


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


def _navigation_enabled(config) -> bool:
    """R12 (ADR-0022): navegação só para sessões que sabem executar um
    redirect — o bearer da Platform. O controller decide e carimba
    `navigation_enabled` no `configurable`; sem ele (SPA do oráculo, eval de
    conhecimento) o turno não vê a tool nem o bloco de prompt."""
    return bool(config.get("configurable", {}).get("navigation_enabled"))


def _answer_messages(state: TurnState, config) -> list:
    """Histórico, contexto embrulhado, pergunta — e, depois dela, perfil do
    usuário (quando presente na config), idioma da resposta e, para intent
    navigate, o marcador que afasta a RESPOSTA PADRÃO (ver bloco NAVEGAÇÃO).

    No modo mentor o bloco de contexto da base **não** entra: o contexto chega
    pela tool `search_lesson`, e um bloco vazio de "contexto recuperado" só
    confundiria o modelo."""
    mode = state.get("mode", "chat")
    parts = [f"{m.role}: {m.content}" for m in state.get("history", [])]

    if mode != "mentor":
        parts.append("Contexto recuperado da base de conhecimento:")
        parts.append(format_knowledge(state.get("knowledge", [])))

    parts.append(f"Pergunta do usuário: {state['question']}")
    if mode == "mentor" and state.get("lesson_id"):
        parts.append(f"Aula em foco (id da plataforma): {state['lesson_id']}")

    profile = config.get("configurable", {}).get("user_profile")
    if profile:
        membership = profile.get("membership") or "None"
        seniority = profile.get("seniority") or "None"
        career_stage = profile.get("careerStage") or "None"
        parts.append(
            f"Perfil do usuário: membership={membership}, seniority={seniority}, careerStage={career_stage}"
        )
    parts.append(f"Idioma da resposta: {state.get('locale', 'pt-BR')}")
    if state.get("intent") == "navigate":
        parts.append("Intenção: navegação (não use a RESPOSTA PADRÃO)")

    system = build_system_prompt(_navigation_enabled(config), mode=mode)
    return [SystemMessage(content=system), HumanMessage(content="\n\n".join(parts))]


def _answer_model(config, enable_tools: bool = True, mode: str = "chat"):
    cfg = config.get("configurable", {})
    injected = cfg.get("answer_model")
    model = injected or build_chat_model()
    if not enable_tools:
        return model
    if mode == "mentor":
        # O mentor só vê `search_lesson` — nada de web_search, notion ou
        # navegação (spec §2.1): o escopo da busca é a aula, não a base geral.
        return model.bind_tools(build_mentor_tools())
    return model.bind_tools(
        model_bound_tools(_navigation_enabled(config), cfg.get("navigation_catalog_text"))
    )


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
    """Resposta do oráculo. Os tokens saem daqui como `on_chat_model_stream` do
    `astream_events` (o modelo strema via callbacks mesmo com `ainvoke`); este
    nó devolve a mensagem completa para o tool loop."""
    cfg = config["configurable"]
    signals = cfg["signals"]

    # Carimbo da PRIMEIRA entrada no estágio de resposta (revisão I2). É a origem
    # de first_token_ms/engine_ms, que o runner fecha, e o marcador que diz ao
    # runner que uma falha daqui em diante é do estágio de resposta — não de
    # gate/retrieve/refuse (revisão I3). Nas re-entradas do tool loop (answer ->
    # tools -> answer) não se mexe: a origem é a primeira entrada.
    if signals.answer_started_at is None:
        signals.answer_started_at = time.monotonic()

    existing_messages = state.get("messages")
    messages = existing_messages or _answer_messages(state, config)
    model = _answer_model(config, enable_tools=cfg.get("enable_tools", True), mode=state.get("mode", "chat"))
    message = await model.ainvoke(messages)

    _fill_usage(signals, message)
    signals.outcome = "answer"

    kb = [s.citation for s in state.get("knowledge", [])]
    # Na primeira entrada, state["messages"] está vazio e `messages` acima é o
    # prompt que acabamos de montar (system + histórico/knowledge/pergunta) —
    # ele precisa entrar no state agora, porque o reducer add_messages só
    # ACUMULA. Sem isso, numa re-entrada do tool loop (answer -> tools ->
    # answer) o state teria só [AIMessage(tool_calls), ToolMessage(...)] e a
    # próxima chamada ao modelo perderia system prompt, histórico, knowledge
    # e a pergunta silenciosamente. Na re-entrada (existing_messages já
    # populado), devolvemos só a resposta nova — o prompt completo já está
    # no state desde a primeira entrada.
    new_messages = [message] if existing_messages else [*messages, message]
    return {
        "messages": new_messages,
        "citations": kb + list(cfg.get("citations", [])),
        "outcome": "answer",
    }
