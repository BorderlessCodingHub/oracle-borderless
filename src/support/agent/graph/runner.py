"""Consumo do grafo em DUAS FASES — ver spec, seção 5.

`BaseHTTPMiddleware` devolve `call_next` quando o StreamingResponse é
*construído*; o corpo SSE é gerado depois, já fora do `async with` que mantém a
sessão async. Logo os nós que tocam o banco (gate, retrieve) precisam rodar
durante o `await start()`, dentro do escopo do request.

`start()` dirige o grafo até o PRIMEIRO token e devolve o gerador do restante.
Dali em diante só há token de LLM e tool HTTP — a mesma invariante que o motor
anterior mantinha por convenção, agora explícita na estrutura.
"""

from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk

from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    TurnDependencies,
    TurnSignals,
)

_TEXT_NODES = ("answer", "refuse")


def _text_of(message) -> str:
    """Anthropic entrega blocos, OpenAI entrega string."""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _token_chunk(payload) -> AgentStreamChunk | None:
    """stream_mode="messages" emite TODA mensagem nova encontrada na saída de
    QUALQUER nó — não só as do modelo de resposta. Isso inclui a `ToolMessage`
    que o `ToolNode` devolve depois de rodar uma tool (ex.: web_search,
    fetch_notion_page), com conteúdo bruto embrulhado em `<<TOOL_CONTENT>>`.

    O contrato SSE só transporta texto do modelo de resposta: por isso o
    filtro dobrado — tipo da mensagem (só AIMessage/AIMessageChunk, nunca
    ToolMessage) E nó de origem (só "answer", nunca "gate", "tools" etc.).
    Texto de preâmbulo antes de uma tool call (AIMessage com content textual +
    tool_calls) continua passando — é paridade com o motor antigo.
    """
    message, metadata = payload
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return None
    if metadata.get("langgraph_node") != "answer":
        return None
    text = _text_of(message)
    return AgentStreamChunk(type="text", text=text) if text else None


def _refusal_chunk(payload) -> AgentStreamChunk | None:
    """O nó refuse é determinístico: não passa por LLM, então nunca aparece em
    stream_mode="messages". O texto chega pelo "updates" e o chunk é sintetizado
    aqui — é o que mantém a recusa instantânea."""
    update = payload.get("refuse")
    if not update or not update.get("answer"):
        return None
    return AgentStreamChunk(type="text", text=update["answer"])


def _absorb(payload, collected: dict) -> None:
    for node in _TEXT_NODES:
        update = payload.get(node)
        if update and update.get("citations") is not None:
            collected["citations"] = list(update["citations"])


class TurnGraphRunner:
    def __init__(
        self,
        graph=None,
        enable_tools: bool = True,
        run_id: str | None = None,
        user_hash: str | None = None,
    ) -> None:
        self._graph = graph or TURN_GRAPH
        self._enable_tools = enable_tools
        # run_id e user_hash só ganham uso na Task 13 (LangSmith); ficam aqui
        # desde já para a fábrica não mudar de assinatura no meio do plano.
        self._run_id = run_id
        self._user_hash = user_hash

    async def start(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
        collected = {"citations": []}
        config = {
            "configurable": {
                "deps": deps,
                "signals": signals,
                "citations": [],
                "enable_tools": self._enable_tools,
                **(extra_config or {}),
            }
        }
        state = {
            "question": question,
            "history": history,
            "knowledge": list(knowledge) if knowledge is not None else [],
            "preset_knowledge": knowledge is not None,
            "messages": [],
        }

        agen = self._graph.astream(state, stream_mode=["updates", "messages"], config=config)

        # FASE 1 — sessão viva. Executa até o primeiro texto sair.
        first = None
        async for mode, payload in agen:
            if mode == "updates":
                _absorb(payload, collected)
                first = _refusal_chunk(payload)
                if first is not None:
                    break
                continue
            first = _token_chunk(payload)
            if first is not None:
                break

        # FASE 2 — devolvida ao controller, consumida fora do escopo da sessão.
        return _resume(first, agen, collected)


async def _resume(first, agen, collected: dict) -> AsyncIterator[AgentStreamChunk]:
    if first is not None:
        yield first
    async for mode, payload in agen:
        if mode == "updates":
            _absorb(payload, collected)
            chunk = _refusal_chunk(payload)
            if chunk is not None:
                yield chunk
            continue
        chunk = _token_chunk(payload)
        if chunk is not None:
            yield chunk
    yield AgentStreamChunk(type="sources", citations=collected["citations"])


def get_turn_graph_runner(
    enable_tools: bool = True,
    run_id: str | None = None,
    user_hash: str | None = None,
) -> "TurnGraphRunner":
    # run_id e user_hash só ganham uso na Task 13 (LangSmith); ficam aqui desde já
    # para a fábrica não mudar de assinatura no meio do plano.
    return TurnGraphRunner(enable_tools=enable_tools, run_id=run_id, user_hash=user_hash)
