"""Grafo fake — implementa TurnGraphPort sem LLM nem banco, emitindo
`GraphEvent` no formato que o runner real produz (ADR-0021).

Preenche `signals` como o grafo real faz, para que testes de integração possam
afirmar que a cadeia grafo → draft → coluna do trace está de fato conectada.

`FakeTurnRun` registra o que `CurrentAsyncSessionContext.get()` devolveu em
cada fase: é o que prova (ADR-0020) que o prelúdio roda dentro de um escopo de
sessão e o stream fora dele.
"""

from typing import AsyncIterator

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import ROOT_NAME, AgentMessage, GraphEvent, KnowledgeSnippet
from src.support.core.context import CurrentAsyncSessionContext


class _Events:
    """Fábrica de GraphEvent com o metadata que o runner real garante."""

    def __init__(self, thread_id: str, run_id: str) -> None:
        self._thread_id = thread_id
        self._run_id = run_id

    def root(self, event: str, data: dict) -> GraphEvent:
        return GraphEvent(event=event, name=ROOT_NAME, run_id=self._run_id, tags=[], metadata={"thread_id": self._thread_id}, parent_ids=[], data=data)

    def node(self, event: str, name: str, data: dict) -> GraphEvent:
        return GraphEvent(event=event, name=name, run_id=f"{name}-run", tags=[], metadata={"thread_id": self._thread_id, "langgraph_node": name}, parent_ids=[self._run_id], data=data)

    def token(self, text: str) -> GraphEvent:
        return GraphEvent(event="on_chat_model_stream", name="ScriptedChatModel", run_id="model-run", tags=[], metadata={"thread_id": self._thread_id, "langgraph_node": "answer"}, parent_ids=[self._run_id, "answer-run"], data={"chunk": {"content": text, "id": "lc_run--fake"}})

    def updates(self, node: str, payload: dict) -> GraphEvent:
        return self.root("on_chain_stream", {"chunk": ["updates", {node: payload}]})

    def values(self, state: dict) -> GraphEvent:
        return self.root("on_chain_stream", {"chunk": ["values", state]})


class FakeTurnRun:
    def __init__(self, graph: "FakeTurnGraph") -> None:
        self._g = graph
        self._ev = _Events(graph.thread_id, graph.run_id)
        self.prelude_session = "not-run"
        self.stream_session = "not-run"

    async def prelude(self) -> AsyncIterator[GraphEvent]:
        self.prelude_session = CurrentAsyncSessionContext.get()
        g, ev = self._g, self._ev
        yield ev.root("on_chain_start", {})
        yield ev.values({"kept": 0})
        yield ev.node("on_chain_start", "gate", {})
        gate = {"retrieve": g._retrieve, "degraded": g._degraded}
        yield ev.node("on_chain_end", "gate", {"output": gate})
        yield ev.updates("gate", gate)
        yield ev.values({**gate, "kept": 0})
        if g._retrieve:
            yield ev.node("on_chain_start", "retrieve", {})
            yield ev.node("on_chain_end", "retrieve", {"output": {"kept": g._retrieval_kept}})
            yield ev.updates("retrieve", {"kept": g._retrieval_kept})
            yield ev.values({**gate, "kept": g._retrieval_kept})
        if g._outcome == "refusal":
            yield ev.node("on_chain_start", "refuse", {})
            yield ev.node("on_chain_end", "refuse", {"output": {"answer": g._answer + " ", "citations": [], "outcome": "refusal"}})
            return
        yield ev.node("on_chain_start", "answer", {})

    async def stream(self) -> AsyncIterator[GraphEvent]:
        self.stream_session = CurrentAsyncSessionContext.get()
        g, ev = self._g, self._ev
        if g._outcome == "refusal":
            refusal = {"answer": g._answer + " ", "citations": [], "outcome": "refusal"}
            yield ev.updates("refuse", refusal)
            yield ev.values({"retrieve": g._retrieve, "degraded": g._degraded, "kept": 0, **refusal})
            yield ev.root("on_chain_end", {"output": {"outcome": "refusal", "citations": []}})
            return
        if g._navigation is not None:
            # Mirror do nó `navigate` real (navigate_node.py): entra, resolve o
            # destino, sai — e SÓ DEPOIS o `answer` retoma os tokens da frase
            # final (spec §5.3: o destino chega ao cliente antes da frase).
            yield ev.node("on_chain_start", "navigate", {})
            yield ev.updates("navigate", {"navigation": g._navigation})
            yield ev.node("on_chain_end", "navigate", {"output": {"navigation": g._navigation}})
        for token in g._answer.split():
            yield ev.token(token + " ")
        final = {"citations": list(g._citations), "outcome": "answer"}
        yield ev.updates("answer", final)
        yield ev.values({"retrieve": g._retrieve, "degraded": g._degraded, "kept": g._retrieval_kept, **final})
        yield ev.node("on_chain_end", "answer", {"output": final})
        root_output = dict(final)
        if g._navigation is not None:
            root_output["navigation"] = g._navigation
        yield ev.root("on_chain_end", {"output": root_output})

    async def aclose(self) -> None:
        return None


class FakeTurnGraph:
    def __init__(
        self,
        answer: str = "resposta",
        citations: list[Citation] | None = None,
        outcome: str = "answer",
        retrieve: bool = True,
        retrieval_kept: int = 1,
        degraded: bool = False,
        tool_calls: int = 0,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        first_token_ms: int = 7,
        engine_ms: int = 42,
        navigation: dict | None = None,
        mentor_distances: list[float] | None = None,
        mentor_embedding: list[float] | None = None,
    ) -> None:
        self._answer = answer
        self._citations = citations or [Citation("notion", "Doc", "https://n/a", "trecho")]
        self._outcome = outcome
        self._retrieve = retrieve
        self._retrieval_kept = retrieval_kept
        self._degraded = degraded
        self._navigation = navigation
        self._tool_calls = tool_calls
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._first_token_ms = first_token_ms
        self._engine_ms = engine_ms
        self._mentor_distances = mentor_distances
        self._mentor_embedding = mentor_embedding
        self.thread_id = "fake-thread"
        self.run_id = "fake-run"
        self.question = None
        self.knowledge = None
        self.received_history = None
        self.received_deps = None
        self.received_signals = None
        self.received_mode = None
        self.received_locale = None
        self.received_extra_config = None
        self.received_lesson_id = None
        self.last_run: FakeTurnRun | None = None

    def with_config(self, **kw) -> "FakeTurnGraph":
        """O controller chama `get_turn_graph_runner(run_id=, user_hash=, thread_id=)`;
        o teste monkeypatcha para `lambda **kw: graph.with_config(**kw)`."""
        if kw.get("thread_id"):
            self.thread_id = kw["thread_id"]
        if kw.get("run_id"):
            self.run_id = kw["run_id"]
        return self

    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps=None,
        signals=None,
        knowledge: list[KnowledgeSnippet] | None = None,
        mode: str = "chat",
        locale: str = "pt-BR",
        extra_config: dict | None = None,
        lesson_id: str | None = None,
    ) -> FakeTurnRun:
        self.question = question
        self.knowledge = knowledge
        self.received_history = history
        self.received_deps = deps
        self.received_signals = signals
        self.received_mode = mode
        self.received_locale = locale
        self.received_extra_config = extra_config
        self.received_lesson_id = lesson_id
        # Mirror da tool `search_lesson` (Task 2): preenche `lesson_distances`/
        # `question_embedding` em place no MESMO dict/lista que o controller
        # guarda em `extra_config` — é assim que o trace pós-stream (Task 5)
        # enxerga o que a tool encontrou, sem precisar de um valor de retorno.
        if mode == "mentor" and extra_config is not None:
            if self._mentor_distances is not None:
                extra_config["lesson_distances"].extend(self._mentor_distances)
            if self._mentor_embedding is not None:
                extra_config["question_embedding"][:] = self._mentor_embedding
        if signals is not None:
            signals.outcome = self._outcome
            signals.gate_retrieve = self._retrieve
            signals.gate_degraded = self._degraded
            signals.retrieval_ran = self._retrieve
            signals.retrieval_kept = self._retrieval_kept
            signals.tool_calls = self._tool_calls
            signals.input_tokens = self._input_tokens
            signals.output_tokens = self._output_tokens
            if self._outcome == "answer":
                signals.answer_started_at = 0.0
                signals.first_token_ms = self._first_token_ms
                signals.engine_ms = self._engine_ms
            if self._navigation is not None:
                # R8: mirror do que o grafo real escreve (navigate_node.py +
                # TurnGraphRunner.run) para que asserções de trace nos testes
                # de integração sejam possíveis sem reimplementar o grafo.
                signals.navigation_called = True
                signals.navigation_access = self._navigation.get("access")
                if mode == "navigate":
                    signals.intent = "navigate"
        self.last_run = FakeTurnRun(self)
        return self.last_run


class _FailingRun:
    def __init__(self, where: str, ev: _Events) -> None:
        self._where = where
        self._ev = ev

    async def prelude(self) -> AsyncIterator[GraphEvent]:
        ev = self._ev
        yield ev.root("on_chain_start", {})
        yield ev.node("on_chain_start", "gate", {})
        yield ev.node("on_chain_end", "gate", {"output": {"retrieve": True, "degraded": False}})
        yield ev.updates("gate", {"retrieve": True, "degraded": False})
        if self._where == "prelude":
            yield ev.node("on_chain_start", "retrieve", {})
            raise RuntimeError("boom: pgvector caiu no prelúdio")
        yield ev.node("on_chain_start", "answer", {})

    async def stream(self) -> AsyncIterator[GraphEvent]:
        yield self._ev.token("ola ")
        raise RuntimeError("boom: engine caiu no meio do stream")

    async def aclose(self) -> None:
        return None


class _FailingGraph:
    where = "stream"

    def __init__(self) -> None:
        self.thread_id = "fake-thread"
        self.run_id = "fake-run"

    def with_config(self, **kw):
        self.thread_id = kw.get("thread_id") or self.thread_id
        self.run_id = kw.get("run_id") or self.run_id
        return self

    def run(self, question, history, deps=None, signals=None, knowledge=None, mode="chat", locale="pt-BR", extra_config=None, lesson_id=None):
        if signals is not None:
            if self.where == "stream":
                signals.outcome = "answer"
            else:
                signals.gate_retrieve = True
                signals.gate_ms = 12
        return _FailingRun(self.where, _Events(self.thread_id, self.run_id))


class FailingInStreamTurnGraph(_FailingGraph):
    """Emite os passos, um token, e quebra em `stream()` — falha do estágio de resposta."""

    where = "stream"


class FailingInPreludeTurnGraph(_FailingGraph):
    """Emite `gate start/end` e `retrieve start`, e quebra em `prelude()` — falha de gate/retrieve (spec §6)."""

    where = "prelude"
