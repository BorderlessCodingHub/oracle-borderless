"""Consumo do grafo em DUAS FASES — ver spec, seção 5.

`BaseHTTPMiddleware` devolve `call_next` quando o StreamingResponse é
*construído*; o corpo SSE é gerado depois, já fora do `async with` que mantém a
sessão async. Logo os nós que tocam o banco (gate, retrieve) precisam rodar
durante o `await start()`, dentro do escopo do request.

`start()` dirige o grafo até a ENTRADA do nó de resposta e devolve o gerador do
restante. Dali em diante só há token de LLM e tool HTTP — a mesma invariante que
o motor anterior mantinha por convenção, agora explícita na estrutura.
"""

import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk

from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    TextChunk,
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


def _is_answer_event(payload) -> bool:
    """O evento veio do nó de resposta? É o que encerra a fase 1 (revisão I4)."""
    _, metadata = payload
    return metadata.get("langgraph_node") == "answer"


def _token_chunk(payload) -> AgentStreamChunk | None:
    """stream_mode="messages" emite TODA mensagem nova encontrada na saída de
    QUALQUER nó — não só as do modelo de resposta. Isso inclui a `ToolMessage`
    que o `ToolNode` devolve depois de rodar uma tool (ex.: web_search,
    fetch_notion_page), com conteúdo bruto embrulhado em `<<TOOL_CONTENT>>`, e
    também o próprio prompt (System/Human) que o nó de resposta devolve no state.

    O contrato SSE só transporta texto do modelo de resposta: por isso o
    filtro dobrado — tipo da mensagem (só AIMessage/AIMessageChunk, nunca
    ToolMessage) E nó de origem (só "answer", nunca "gate", "tools" etc.).
    Texto de preâmbulo antes de uma tool call (AIMessage com content textual +
    tool_calls) continua passando — é paridade com o motor antigo.
    """
    message, _ = payload
    if not isinstance(message, (AIMessage, AIMessageChunk)):
        return None
    if not _is_answer_event(payload):
        return None
    text = _text_of(message)
    return TextChunk(text=text) if text else None


def _refusal_chunk(payload) -> AgentStreamChunk | None:
    """O nó refuse é determinístico: não passa por LLM, então nunca aparece em
    stream_mode="messages". O texto chega pelo "updates" e o chunk é sintetizado
    aqui — é o que mantém a recusa instantânea."""
    update = payload.get("refuse")
    if not update or not update.get("answer"):
        return None
    return TextChunk(text=update["answer"])


def _absorb(payload, collected: dict) -> None:
    for node in _TEXT_NODES:
        update = payload.get(node)
        if update and update.get("citations") is not None:
            collected["citations"] = list(update["citations"])


def _mark_first_token(signals: TurnSignals) -> None:
    """Primeiro TEXTO vindo do nó de resposta, contado desde a entrada nesse nó.

    Fora do caminho de resposta (`answer_started_at is None`, isto é: recusa)
    nada é marcado — a recusa é texto canônico e não entra nas médias do motor.
    """
    if signals.answer_started_at is None or signals.first_token_ms is not None:
        return
    signals.first_token_ms = int((time.monotonic() - signals.answer_started_at) * 1000)


def _mark_engine_end(signals: TurnSignals) -> None:
    """Fim do stream: total do estágio de resposta (inclui o tool loop)."""
    if signals.answer_started_at is None:
        return
    signals.engine_ms = int((time.monotonic() - signals.answer_started_at) * 1000)


def _initial_state(
    question: str, history: list[AgentMessage], knowledge: list[KnowledgeSnippet] | None
) -> dict:
    """`preset_knowledge` liga a aresta que pula gate/retrieve (eval adversarial)."""
    return {
        "question": question,
        "history": history,
        "knowledge": list(knowledge) if knowledge is not None else [],
        "preset_knowledge": knowledge is not None,
        "messages": [],
    }


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
        self._run_id = run_id
        self._user_hash = user_hash

    def _config(self, deps: TurnDependencies, signals: TurnSignals, extra_config: dict | None) -> dict:
        config: dict = {
            "configurable": {
                "deps": deps,
                "signals": signals,
                "citations": [],
                "enable_tools": self._enable_tools,
                **(extra_config or {}),
            }
        }
        # run_id/metadata ficam no TOPO do config (contrato do LangGraph/LangSmith),
        # não em "configurable". O e-mail em claro nunca entra aqui — só o hash.
        if self._run_id is not None:
            config["run_id"] = self._run_id
        if self._user_hash is not None:
            config["metadata"] = {"user_hash": self._user_hash}
        return config

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
        agen = self._graph.astream(
            _initial_state(question, history, knowledge),
            stream_mode=["updates", "messages"],
            config=self._config(deps, signals, extra_config),
        )

        # FASE 1 — sessão viva. Para na ENTRADA do nó de resposta (revisão I4).
        #
        # O critério NÃO é "o primeiro texto": quando o modelo abre com uma
        # AIMessage só de tool_calls (content vazio — a forma comum de
        # Anthropic/OpenAI), nenhum chunk de texto é produzido e o laço
        # answer -> tools -> answer inteiro rodaria aqui dentro, segurando a
        # conexão Postgres do request durante chamadas HTTP externas. O critério
        # é o PRIMEIRO evento "messages" do nó `answer` — mesmo que ele não
        # renda texto (o `first` vai None para o `_resume`, como já ia).
        #
        # Gate e retrieve precedem estritamente o `answer` no grafo, então a
        # invariante de sessão não só se mantém como fica mais apertada.
        first = None
        deferred: Exception | None = None
        try:
            async for mode, payload in agen:
                if mode == "updates":
                    _absorb(payload, collected)
                    first = _refusal_chunk(payload)
                    if first is not None:
                        break
                    continue
                if not _is_answer_event(payload):
                    continue
                first = _token_chunk(payload)
                if first is not None:
                    _mark_first_token(signals)
                break
        except Exception as exc:
            # Revisão I3 — de onde veio a falha decide quem a trata:
            #
            # - gate/retrieve/refuse (`answer_started_at is None`): sobe agora,
            #   ainda dentro da sessão, e o rollback do DBSessionMiddleware pega
            #   (spec, seção 7). Turno sem contexto é pior que erro visível.
            # - estágio de resposta (o nó `answer` já foi carimbado): a exceção
            #   é ADIADA para o `_resume`. Se subisse aqui, viraria um 500 seco:
            #   o middleware faria rollback (perdendo a mensagem do usuário) e
            #   NENHUMA linha de agent_traces com outcome="error" seria gravada
            #   — justamente o trace mais valioso. Adiando, cai no `except` que
            #   o controller já tem: evento SSE de erro + trace persistido, com
            #   a mensagem do usuário já commitada. É a paridade com o motor
            #   antigo, onde a chamada ao LLM era preguiçosa dentro do corpo SSE.
            if signals.answer_started_at is None:
                raise
            deferred = exc

        # FASE 2 — devolvida ao controller, consumida fora do escopo da sessão.
        return _resume(first, agen, collected, signals, deferred)


async def _resume(
    first,
    agen,
    collected: dict,
    signals: TurnSignals,
    deferred: Exception | None = None,
) -> AsyncIterator[AgentStreamChunk]:
    # Primeira coisa: relançar a falha do estágio de resposta capturada na fase 1
    # (revisão I3), para que ela chegue ao `except` do controller.
    if deferred is not None:
        raise deferred
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
            _mark_first_token(signals)
            yield chunk
    _mark_engine_end(signals)
    yield SourcesChunk(citations=collected["citations"])


def get_turn_graph_runner(
    enable_tools: bool = True,
    run_id: str | None = None,
    user_hash: str | None = None,
) -> "TurnGraphRunner":
    return TurnGraphRunner(enable_tools=enable_tools, run_id=run_id, user_hash=user_hash)
