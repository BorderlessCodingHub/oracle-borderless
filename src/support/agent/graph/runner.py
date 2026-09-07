"""Consumo do grafo em DUAS FASES, ambas no corpo SSE — ver ADR-0020.

`run()` monta o gerador do grafo com `stream_mode=["updates", "messages",
"debug"]` e devolve um `_TurnRun`. `prelude()` dirige o grafo até a ENTRADA
real do nó de resposta (evento `task` do modo `debug`) ou até a recusa; é a
fase que toca o banco e o controller a consome dentro de `async_session_scope()`.
`stream()` é o resto — token de LLM e tool HTTP — e roda sem sessão.

O modo `debug` existe aqui por um motivo só: ele avisa quando um nó COMEÇA.
`updates` só chega no fim do nó, então sem o `task` o "started" de um passo
seria sintetizado junto com o "finished" e a linha do tempo não acenderia
passo a passo. Do payload `debug` o emitter lê SÓ `type` e `payload.name` — o
`input` é o state inteiro (com o `knowledge` recuperado) e nunca sai daqui
(regra 4).

Desde o ADR-0019 cada nó vira um `StepChunk`. A tradução para eventos AG-UI
NÃO é daqui — mora em `src/app/api/streaming/`. Este módulo só fala em
dataclasses do port.
"""

import json
import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
    TurnDependencies,
    TurnRun,
    TurnSignals,
)

_CITATION_NODES = ("answer", "refuse")
_TOOL_CONTENT_OPEN = "<<TOOL_CONTENT>>"
_TOOL_CONTENT_CLOSE = "<</TOOL_CONTENT>>"
# tools.py devolve falha capturada como texto "(falha ao ...)" dentro do envelope.
_TOOL_FAILURE_PREFIX = "(falha"
# F1 / regra 4 / spec §12: nenhum evento pode carregar o page_id do Notion.
# START/END/RESULT saem para toda tool (só o status, nunca conteúdo); ARGS só
# sai para tools cujos argumentos são exibíveis na UI — hoje, só web_search.
_ARGS_VISIBLE_TOOLS = frozenset({"web_search"})

# Nós que viram passo na linha do tempo. `tools` não: tool calls têm eventos
# próprios (START/ARGS/END/RESULT).
_STEP_NODES = frozenset({"gate", "retrieve", "refuse", "answer"})


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


def _task_name(payload: dict) -> str | None:
    """Nome do nó de um evento `debug` do tipo `task` (entrada de nó). None para
    `task_result`, `checkpoint` ou payload malformado. Nada além do nome é lido."""
    if not isinstance(payload, dict) or payload.get("type") != "task":
        return None
    inner = payload.get("payload")
    return inner.get("name") if isinstance(inner, dict) else None


def _step_detail(name: str, signals: TurnSignals) -> dict | None:
    """O que a UI mostra ao lado do passo. Lido dos `signals`, que o nó já
    escreveu quando o seu update chega."""
    if name == "gate":
        return {"retrieve": signals.gate_retrieve, "degraded": signals.gate_degraded}
    if name == "retrieve":
        return {"kept": signals.retrieval_kept}
    return None


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


class TurnEmitter:
    """Traduz os eventos brutos do LangGraph (`debug`, `updates` e `messages`)
    em chunks do port, guardando o pouco de estado que isso exige: quais passos
    já abriram e as citações coletadas. Um por run.

    O `started` de um passo vem do `task` do modo `debug` (entrada real do nó);
    o `finished` vem do `update` (fim do nó, quando os `signals` já têm o
    `detail`). `step_started` é idempotente, então um update sem `task` antes
    (fakes que não emitem `debug`) ainda sintetiza o `started`.
    """

    def __init__(self, signals: TurnSignals) -> None:
        self._signals = signals
        self._steps_started: set[str] = set()
        self.citations: list[Citation] = []
        self._tool_started: set[str] = set()
        self._tool_ended: set[str] = set()
        self._index_to_id: dict[int, str] = {}
        self._tool_names: dict[str, str] = {}

    def step_started(self, name: str) -> list[AgentStreamChunk]:
        if name in self._steps_started:
            return []
        self._steps_started.add(name)
        return [StepChunk(name=name, phase="started")]

    def step_finished(self, name: str) -> list[AgentStreamChunk]:
        return [
            *self.step_started(name),
            StepChunk(name=name, phase="finished", detail=_step_detail(name, self._signals)),
        ]

    def on_debug(self, payload: dict) -> list[AgentStreamChunk]:
        """Um payload de stream_mode="debug". Só `type == "task"` (entrada de
        nó) e só o nome — o `input` do payload é o state inteiro e nunca sai
        daqui (regra 4). `task_result` é ignorado: o `finished` vem do update."""
        name = _task_name(payload)
        if name in _STEP_NODES:
            return self.step_started(name)
        return []

    def on_update(self, payload: dict) -> list[AgentStreamChunk]:
        """Um payload de stream_mode="updates": {nó: saída do nó}."""
        out: list[AgentStreamChunk] = []
        for node, update in payload.items():
            update = update or {}
            if node in ("gate", "retrieve"):
                out += self.step_finished(node)
            elif node == "refuse":
                # O nó refuse é determinístico: não passa por LLM, então nunca
                # aparece em "messages". O texto chega por aqui e o chunk é
                # sintetizado — é o que mantém a recusa instantânea.
                out += self.step_finished("refuse")
                if update.get("answer"):
                    out.append(TextChunk(text=update["answer"]))
            elif node == "answer":
                out += self.step_started("answer")
                out += self._tool_ends_from(update)
            elif node == "tools":
                out += self._tool_results_from(update)
            if node in _CITATION_NODES and update.get("citations") is not None:
                self.citations = list(update["citations"])
        return out

    def on_message(self, payload) -> list[AgentStreamChunk]:
        """Um payload de stream_mode="messages": (mensagem, metadata).

        Só o nó `answer` interessa, e dele só texto de AIMessage/AIMessageChunk:
        a ToolMessage que o ToolNode devolve (conteúdo bruto em <<TOOL_CONTENT>>)
        e o próprio prompt (System/Human) que o nó devolve no state nunca viram
        texto. Preâmbulo antes de uma tool call continua passando.
        """
        message, _ = payload
        if not _is_answer_event(payload):
            return []
        out = self.step_started("answer")
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return out
        # F5: o preâmbulo (texto que acompanha uma tool call na MESMA
        # AIMessage) tem que sair antes da tool call no fio — senão a UI vê
        # TOOL_CALL_* antes do TEXT_MESSAGE_START do mesmo turno.
        text = _text_of(message)
        if text:
            out.append(TextChunk(text=text))
        out += self._tool_calls_from(message)
        return out

    # --- tool calls -------------------------------------------------------

    def _tool_start(self, tc_id: str, name: str) -> list[AgentStreamChunk]:
        if tc_id in self._tool_started:
            return []
        self._tool_started.add(tc_id)
        self._tool_names[tc_id] = name
        return [ToolCallStartChunk(id=tc_id, name=name)]

    def _tool_end(self, tc_id: str) -> list[AgentStreamChunk]:
        if tc_id not in self._tool_started or tc_id in self._tool_ended:
            return []
        self._tool_ended.add(tc_id)
        return [ToolCallEndChunk(id=tc_id)]

    def _tool_calls_from(self, message) -> list[AgentStreamChunk]:
        """Tool calls de uma mensagem do modelo, em duas formas:

        - fragmentos (`tool_call_chunks`, provedor em streaming): id+nome no
          primeiro, só `index` nos seguintes — o mapa index -> id resolve;
        - a chamada inteira (`tool_calls`, provedor sem streaming ou fake de
          teste): start, args com o JSON completo e end de uma vez.
        """
        out: list[AgentStreamChunk] = []
        fragments = getattr(message, "tool_call_chunks", None) or []
        if fragments:
            for frag in fragments:
                tc_id = frag.get("id")
                index = frag.get("index")
                if tc_id and index is not None:
                    self._index_to_id[index] = tc_id
                if not tc_id and index is not None:
                    tc_id = self._index_to_id.get(index)
                if not tc_id:
                    continue
                if frag.get("name"):
                    out += self._tool_start(tc_id, frag["name"])
                if (
                    tc_id in self._tool_started
                    and frag.get("args")
                    and self._tool_names.get(tc_id) in _ARGS_VISIBLE_TOOLS
                ):
                    out.append(ToolCallArgsChunk(id=tc_id, delta=frag["args"]))
            return out
        for call in getattr(message, "tool_calls", None) or []:
            tc_id = call.get("id")
            if not tc_id or tc_id in self._tool_started:
                continue
            name = call.get("name") or ""
            out += self._tool_start(tc_id, name)
            if name in _ARGS_VISIBLE_TOOLS:
                out.append(ToolCallArgsChunk(id=tc_id, delta=json.dumps(call.get("args") or {}, ensure_ascii=False)))
            out += self._tool_end(tc_id)
        return out

    def _tool_ends_from(self, update: dict) -> list[AgentStreamChunk]:
        """Update do nó answer: a AIMessage final fecha as tool calls que ainda
        estão abertas. Passa antes por `_tool_calls_from` porque, sem streaming,
        a chamada pode estar aparecendo aqui pela primeira vez."""
        out: list[AgentStreamChunk] = []
        for message in update.get("messages") or []:
            if not isinstance(message, AIMessage):
                continue
            out += self._tool_calls_from(message)
            for call in message.tool_calls or []:
                if call.get("id"):
                    out += self._tool_end(call["id"])
        return out

    def _tool_results_from(self, update: dict) -> list[AgentStreamChunk]:
        """Update do nó tools: uma ToolMessage por chamada executada."""
        out: list[AgentStreamChunk] = []
        for message in update.get("messages") or []:
            if not isinstance(message, ToolMessage):
                continue
            out += self._tool_end(message.tool_call_id)
            out.append(ToolCallResultChunk(id=message.tool_call_id, status=_tool_status(message)))
        return out

    def finish(self) -> list[AgentStreamChunk]:
        """Fim do stream: fecha o passo de resposta (se abriu) e entrega as fontes."""
        out: list[AgentStreamChunk] = []
        if "answer" in self._steps_started:
            out.append(StepChunk(name="answer", phase="finished"))
        out.append(SourcesChunk(citations=list(self.citations)))
        return out


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


class _TurnRun:
    """Implementa `TurnRun` por cima de um gerador `astream` do LangGraph.

    O `break` no `async for` NÃO fecha o gerador do grafo — é isso que permite
    `stream()` retomar exatamente de onde `prelude()` parou. Enquanto ninguém
    itera, o LangGraph não avança: o nó `answer` só começa quando `stream()` é
    iterado, já fora do escopo de sessão.
    """

    def __init__(self, agen, emitter: TurnEmitter, signals: TurnSignals) -> None:
        self._agen = agen
        self._emitter = emitter
        self._signals = signals
        self._prelude_done = False

    async def prelude(self) -> AsyncIterator[AgentStreamChunk]:
        async for mode, payload in self._agen:
            if mode == "debug":
                for chunk in self._emitter.on_debug(payload):
                    yield chunk
                if _task_name(payload) == "answer":
                    break  # entrada REAL do nó de resposta (D3)
            elif mode == "updates":
                for chunk in self._emitter.on_update(payload):
                    yield chunk
                if "refuse" in payload:
                    break  # a recusa é determinística e termina o grafo
            elif _is_answer_event(payload):
                # Defensivo: não é esperado ver "messages" do answer antes do
                # seu `task`, mas se vier é a entrada — nada de texto se perde.
                for chunk in self._emitter.on_message(payload):
                    if isinstance(chunk, TextChunk):
                        _mark_first_token(self._signals)
                    yield chunk
                break
            # "messages" de outros nós (structured output do gate) são ignorados.
        self._prelude_done = True

    async def stream(self) -> AsyncIterator[AgentStreamChunk]:
        if not self._prelude_done:
            raise RuntimeError("stream() chamado antes de prelude() esgotar — a fase 1 toca o banco e precisa terminar dentro do escopo de sessão")
        async for mode, payload in self._agen:
            if mode == "debug":
                chunks = self._emitter.on_debug(payload)  # re-entradas do answer: idempotente
            elif mode == "updates":
                chunks = self._emitter.on_update(payload)
            else:
                chunks = self._emitter.on_message(payload)
            for chunk in chunks:
                if isinstance(chunk, TextChunk):
                    _mark_first_token(self._signals)
                yield chunk
        _mark_engine_end(self._signals)
        for chunk in self._emitter.finish():
            yield chunk


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

    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> TurnRun:
        agen = self._graph.astream(
            _initial_state(question, history, knowledge),
            stream_mode=["updates", "messages", "debug"],
            config=self._config(deps, signals, extra_config),
        )
        return _TurnRun(agen, TurnEmitter(signals), signals)


def get_turn_graph_runner(
    enable_tools: bool = True,
    run_id: str | None = None,
    user_hash: str | None = None,
) -> "TurnGraphRunner":
    return TurnGraphRunner(enable_tools=enable_tools, run_id=run_id, user_hash=user_hash)
