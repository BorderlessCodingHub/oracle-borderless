"""Grafo fake — implementa TurnGraphPort sem LLM nem banco.

Preenche `signals` como o grafo real faz, para que testes de integração possam
afirmar que a cadeia grafo → draft → coluna do trace está de fato conectada.

`FakeTurnRun` registra o que `CurrentAsyncSessionContext.get()` devolveu em
cada fase: é o que prova (ADR-0020) que o prelúdio roda dentro de um escopo de
sessão e o stream fora dele.
"""

from typing import AsyncIterator

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
)
from src.support.core.context import CurrentAsyncSessionContext


class FakeTurnRun:
    def __init__(self, graph: "FakeTurnGraph") -> None:
        self._g = graph
        self.prelude_session = "not-run"
        self.stream_session = "not-run"

    async def prelude(self) -> AsyncIterator[AgentStreamChunk]:
        self.prelude_session = CurrentAsyncSessionContext.get()
        yield StepChunk(name="gate", phase="started")
        yield StepChunk(name="gate", phase="finished", detail={"retrieve": self._g._retrieve, "degraded": self._g._degraded})
        if self._g._retrieve:
            yield StepChunk(name="retrieve", phase="started")
            yield StepChunk(name="retrieve", phase="finished", detail={"kept": self._g._retrieval_kept})
        if self._g._outcome == "refusal":
            yield StepChunk(name="refuse", phase="started")
            yield StepChunk(name="refuse", phase="finished")
            yield TextChunk(text=self._g._answer + " ")
            return
        yield StepChunk(name="answer", phase="started")

    async def stream(self) -> AsyncIterator[AgentStreamChunk]:
        self.stream_session = CurrentAsyncSessionContext.get()
        if self._g._outcome == "refusal":
            yield SourcesChunk(citations=[])
            return
        for token in self._g._answer.split():
            yield TextChunk(text=token + " ")
        yield StepChunk(name="answer", phase="finished")
        yield SourcesChunk(citations=list(self._g._citations))


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
    ) -> None:
        self._answer = answer
        self._citations = citations or [Citation("notion", "Doc", "https://n/a", "trecho")]
        self._outcome = outcome
        self._retrieve = retrieve
        self._retrieval_kept = retrieval_kept
        self._degraded = degraded
        self._tool_calls = tool_calls
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._first_token_ms = first_token_ms
        self._engine_ms = engine_ms
        self.question = None
        self.knowledge = None
        self.received_history = None
        self.received_deps = None
        self.received_signals = None
        self.last_run: FakeTurnRun | None = None

    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps=None,
        signals=None,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> FakeTurnRun:
        self.question = question
        self.knowledge = knowledge
        self.received_history = history
        self.received_deps = deps
        self.received_signals = signals
        if signals is not None:
            signals.outcome = self._outcome
            signals.gate_retrieve = self._retrieve
            signals.gate_degraded = self._degraded
            signals.retrieval_ran = self._retrieve
            signals.retrieval_kept = self._retrieval_kept
            signals.tool_calls = self._tool_calls
            signals.input_tokens = self._input_tokens
            signals.output_tokens = self._output_tokens
            # Quem mede a latência do motor é o grafo (revisão I2); o fake
            # preenche como o runner real. Na recusa nenhum modelo roda.
            if self._outcome == "answer":
                signals.answer_started_at = 0.0
                signals.first_token_ms = self._first_token_ms
                signals.engine_ms = self._engine_ms
        self.last_run = FakeTurnRun(self)
        return self.last_run


class _FailingRun:
    def __init__(self, where: str) -> None:
        self._where = where

    async def prelude(self) -> AsyncIterator[AgentStreamChunk]:
        yield StepChunk(name="gate", phase="started")
        yield StepChunk(name="gate", phase="finished", detail={"retrieve": True, "degraded": False})
        if self._where == "prelude":
            raise RuntimeError("boom: pgvector caiu no prelúdio")
        yield StepChunk(name="answer", phase="started")

    async def stream(self) -> AsyncIterator[AgentStreamChunk]:
        yield TextChunk(text="ola ")
        raise RuntimeError("boom: engine caiu no meio do stream")


class FailingInStreamTurnGraph:
    """Emite os passos, um token, e quebra em `stream()` — falha do estágio de resposta."""

    def run(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        if signals is not None:
            signals.outcome = "answer"
        return _FailingRun("stream")


class FailingInPreludeTurnGraph:
    """Emite `gate started/finished` e quebra em `prelude()` — falha de gate/retrieve (spec §8, D2)."""

    def run(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        if signals is not None:
            signals.gate_retrieve = True
            signals.gate_ms = 12
        return _FailingRun("prelude")
