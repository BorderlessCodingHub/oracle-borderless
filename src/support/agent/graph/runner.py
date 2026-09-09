"""Consumo do grafo via `astream_events` em DUAS FASES, ambas no corpo SSE —
ver ADR-0020 (fases) e ADR-0021 (formato).

`run()` monta o gerador `astream_events(version="v2", stream_mode=["values",
"updates"])` e devolve um `_TurnRun`. `prelude()` dirige o grafo até a ENTRADA
real do nó de resposta (`on_chain_start` do nó `answer`) ou até o fim da recusa
(`on_chain_end` do nó `refuse`); é a fase que toca o banco e o controller a
consome dentro de `async_session_scope()`. `stream()` é o resto — tokens, tools,
chunks de `updates`/`values`, fim do `answer` e do raiz — e roda sem sessão.
O grafo não espera o consumidor (ver `_TurnRun`): a separação das fases vem da
ordem dos eventos, não de uma pausa.

Todo evento passa pelo `EventRedactor` antes de cruzar o port: é a ÚNICA
barreira entre o state do grafo (knowledge, prompt, conteúdo de tool) e o
cliente (regra 4). Nada aqui conhece SSE ou a camada `app`.
"""

import time
from typing import AsyncIterator

from langchain_core.messages import ToolMessage

from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    GraphEvent,
    KnowledgeSnippet,
    TurnDependencies,
    TurnRun,
    TurnSignals,
)

_TOOL_CONTENT_OPEN = "<<TOOL_CONTENT>>"
_TOOL_CONTENT_CLOSE = "<</TOOL_CONTENT>>"
# tools.py devolve falha capturada como texto "(falha ao ...)" dentro do envelope.
_TOOL_FAILURE_PREFIX = "(falha"
# Regra 4: nenhum evento pode carregar o page_id do Notion. `on_tool_start` só
# leva `input` para tools cujos argumentos são exibíveis na UI — hoje, web_search.
_ARGS_VISIBLE_TOOLS = frozenset({"web_search"})

# Nós que viram passo na linha do tempo. `tools` não: tool calls têm eventos
# próprios (on_tool_start/end/error).
_STEP_NODES = frozenset({"gate", "retrieve", "refuse", "answer"})

# O que do `metadata` do LangChain/LangGraph pode sair. Fora: user_hash (hash do
# e-mail), langgraph_path/triggers/checkpoint_ns (ruído interno), lc_versions.
_METADATA_KEYS = ("langgraph_node", "langgraph_step", "thread_id", "ls_provider", "ls_model_name")

# Chaves do state copiadas tal como estão pela projeção. `knowledge` vira
# `kept`; `citations` é copiada como lista; tudo o mais cai.
_STATE_KEYS = ("retrieve", "degraded", "answer", "outcome")


def _text_of(message) -> str:
    """Anthropic entrega blocos, OpenAI entrega string."""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _tool_status(message: ToolMessage) -> str:
    """Só o status atravessa o port. O conteúdo em si fica no LangSmith (regra 4)."""
    if getattr(message, "status", "success") == "error":
        return "error"
    text = _text_of(message).strip()
    if text.startswith(_TOOL_CONTENT_OPEN):
        text = text[len(_TOOL_CONTENT_OPEN):].strip()
    if text.endswith(_TOOL_CONTENT_CLOSE):
        text = text[: -len(_TOOL_CONTENT_CLOSE)].strip()
    return "error" if text.startswith(_TOOL_FAILURE_PREFIX) else "ok"


def _project(state) -> dict:
    """Projeção pública do state (spec 07/09, §1.2). Aplicada a saídas de nó, a
    cada valor de um chunk `updates` e ao snapshot de `values`."""
    if not isinstance(state, dict):
        return {}
    out = {key: state[key] for key in _STATE_KEYS if key in state}
    if "knowledge" in state:
        out["kept"] = len(state["knowledge"] or [])
    if "citations" in state:
        out["citations"] = list(state["citations"] or [])
    return out


class EventRedactor:
    """Allowlist + projeção. Um por run: guarda se o `answer` já abriu (o tool
    loop re-entra no nó e o passo não pode reabrir) e segura o `on_chain_end`
    do `answer` para que ele saia uma vez só, antes do fim do raiz."""

    def __init__(self) -> None:
        self._answer_started = False
        self.pending_answer_end: GraphEvent | None = None

    def redact(self, raw: dict) -> GraphEvent | None:
        event = raw.get("event", "")
        name = raw.get("name", "") or ""
        metadata = raw.get("metadata") or {}
        node = metadata.get("langgraph_node")
        parent_ids = list(raw.get("parent_ids") or [])
        data = raw.get("data") or {}

        if not parent_ids:
            payload = self._root(event, data)
        elif name in _STEP_NODES and node == name and event in ("on_chain_start", "on_chain_end"):
            payload = self._node(event, name, data)
        elif event == "on_chat_model_stream" and node == "answer":
            payload = self._token(data)
        elif event in ("on_tool_start", "on_tool_end", "on_tool_error") and node == "tools":
            payload = self._tool(event, name, data)
        else:
            payload = None
        if payload is None:
            return None

        redacted = GraphEvent(
            event=event,
            name=name,
            run_id=str(raw.get("run_id", "")),
            # tags passam sem filtro por decisão da spec (§1.2): hoje só seq:step:N/graph:step:N.
            tags=list(raw.get("tags") or []),
            metadata={key: metadata[key] for key in _METADATA_KEYS if key in metadata},
            parent_ids=parent_ids,
            data=payload,
        )
        if event == "on_chain_end" and name == "answer":
            self.pending_answer_end = redacted  # sai antes do on_chain_end do raiz
            return None
        return redacted

    def _root(self, event: str, data: dict) -> dict | None:
        if event == "on_chain_start":
            return {}
        if event == "on_chain_end":
            return {"output": _project(data.get("output"))}
        if event == "on_chain_stream":
            chunk = data.get("chunk")
            if not (isinstance(chunk, (tuple, list)) and len(chunk) == 2):
                return None
            mode, payload = chunk
            if mode == "updates":
                if not isinstance(payload, dict):
                    return None
                return {"chunk": ["updates", {n: _project(u) for n, u in (payload or {}).items()}]}
            if mode == "values":
                return {"chunk": ["values", _project(payload)]}
        return None

    def _node(self, event: str, name: str, data: dict) -> dict | None:
        if event == "on_chain_start":
            if name == "answer":
                if self._answer_started:
                    return None
                self._answer_started = True
            return {}
        return {"output": _project(data.get("output"))}

    def _token(self, data: dict) -> dict | None:
        chunk = data.get("chunk")
        text = _text_of(chunk)
        if not text:
            return None  # chunk só de tool_call_chunks, ou o vazio final do provider
        return {"chunk": {"content": text, "id": getattr(chunk, "id", None)}}

    def _tool(self, event: str, name: str, data: dict) -> dict:
        if event == "on_tool_start":
            return {"input": data.get("input")} if name in _ARGS_VISIBLE_TOOLS else {}
        if event == "on_tool_error":
            return {"output": {"status": "error", "tool_call_id": data.get("tool_call_id")}}
        output = data.get("output")
        # fail closed: saída fora do formato do ToolNode não vira "ok" por acaso
        status = _tool_status(output) if isinstance(output, ToolMessage) else "error"
        return {"output": {"status": status, "tool_call_id": getattr(output, "tool_call_id", None)}}


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
    question: str,
    history: list[AgentMessage],
    knowledge: list[KnowledgeSnippet] | None,
    mode: str = "chat",
    locale: str = "pt-BR",
) -> dict:
    """`preset_knowledge` liga a aresta que pula gate/retrieve (eval adversarial).

    `mode`/`locale` vêm do input do cliente. Em `mode == "navigate"` a barra já
    fixou a intenção: o state nasce com `intent`/`retrieve`/`search_query`/
    `degraded` preset, sem passar pelo gate (spec §5.3; as arestas que usam
    isso são a Task 4)."""
    state = {
        "question": question,
        "history": history,
        "knowledge": list(knowledge) if knowledge is not None else [],
        "preset_knowledge": knowledge is not None,
        "messages": [],
        "mode": mode,
        "locale": locale,
        "navigation": None,
    }
    if mode == "navigate":
        # A barra fixa a intenção: sem gate, sem RAG, sem recusa (spec §5.3).
        state.update({"intent": "navigate", "retrieve": False, "search_query": "", "degraded": False})
    return state


def _is_answer_entry(event: GraphEvent) -> bool:
    return event.event == "on_chain_start" and event.name == "answer" and not event.is_root


def _is_refuse_end(event: GraphEvent) -> bool:
    return event.event == "on_chain_end" and event.name == "refuse" and not event.is_root


def _is_root_end(event: GraphEvent) -> bool:
    return event.event == "on_chain_end" and event.is_root


class _TurnRun:
    """Implementa `TurnRun` por cima do gerador `astream_events` do LangGraph.

    O `astream_events` NÃO é dirigido pelo consumidor: ele roda o grafo numa
    task própria e empilha os eventos numa fila sem limite. Parar de iterar (o
    `break` do `prelude()`) não pausa o grafo — o nó `answer` pode começar antes
    de `stream()` ser iterado. O que a fase 1 garante é mais estreito, e basta:
    a ORDEM dos eventos assegura que gate/retrieve/refuse já terminaram quando a
    entrada do `answer` é entregue, e nenhum nó a partir do `answer` toca `deps`
    (banco). Nenhum trabalho de banco escapa do escopo de sessão, ainda que o
    modelo já possa estar rodando enquanto o controller fecha o escopo.

    `aclose()` cancela a task do grafo quando o turno é abandonado (desconexão,
    falha): sem isso ela seguiria chamando LLM e tools até o GC fechar o gerador.
    """

    def __init__(self, agen, redactor: EventRedactor, signals: TurnSignals) -> None:
        self._agen = agen
        self._redactor = redactor
        self._signals = signals
        self._prelude_done = False

    async def prelude(self) -> AsyncIterator[GraphEvent]:
        async for raw in self._agen:
            event = self._redactor.redact(raw)
            if event is None:
                continue
            yield event
            if _is_answer_entry(event) or _is_refuse_end(event):
                break
        self._prelude_done = True

    async def stream(self) -> AsyncIterator[GraphEvent]:
        if not self._prelude_done:
            raise RuntimeError("stream() chamado antes de prelude() esgotar — a fase 1 toca o banco e precisa terminar dentro do escopo de sessão")
        async for raw in self._agen:
            event = self._redactor.redact(raw)
            if event is None:
                continue
            if event.event == "on_chat_model_stream":
                _mark_first_token(self._signals)
            if _is_root_end(event):
                _mark_engine_end(self._signals)
                if self._redactor.pending_answer_end is not None:
                    yield self._redactor.pending_answer_end
            yield event

    async def aclose(self) -> None:
        await self._agen.aclose()


class TurnGraphRunner:
    def __init__(
        self,
        graph=None,
        enable_tools: bool = True,
        run_id: str | None = None,
        user_hash: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        self._graph = graph or TURN_GRAPH
        self._enable_tools = enable_tools
        self._run_id = run_id
        self._user_hash = user_hash
        self._thread_id = thread_id

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
        # thread_id em `configurable` é a convenção do LangGraph: ele o copia
        # para o `metadata` de todo evento — é como o cliente descobre a conversa.
        if self._thread_id is not None:
            config["configurable"]["thread_id"] = self._thread_id
        # run_id/metadata ficam no TOPO do config (contrato do LangGraph/LangSmith),
        # não em "configurable". O e-mail em claro nunca entra aqui — só o hash,
        # e o hash não passa pela allowlist do redator.
        if self._run_id is not None:
            config["run_id"] = self._run_id
        if self._user_hash is not None:
            config["metadata"] = {"user_hash": self._user_hash}
        return config

    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        mode: str = "chat",
        locale: str = "pt-BR",
        extra_config: dict | None = None,
    ) -> TurnRun:
        agen = self._graph.astream_events(
            _initial_state(question, history, knowledge, mode=mode, locale=locale),
            config=self._config(deps, signals, extra_config),
            version="v2",
            stream_mode=["values", "updates"],
        )
        return _TurnRun(agen, EventRedactor(), signals)


def get_turn_graph_runner(
    enable_tools: bool = True,
    run_id: str | None = None,
    user_hash: str | None = None,
    thread_id: str | None = None,
) -> "TurnGraphRunner":
    return TurnGraphRunner(enable_tools=enable_tools, run_id=run_id, user_hash=user_hash, thread_id=thread_id)
