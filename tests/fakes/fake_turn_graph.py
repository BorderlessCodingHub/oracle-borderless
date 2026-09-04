"""Grafo fake — implementa TurnGraphPort sem LLM nem banco.

Preenche `signals` como o grafo real faz, para que testes de integração possam
afirmar que a cadeia grafo → draft → coluna do trace está de fato conectada.
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

    async def start(
        self,
        question: str,
        history: list[AgentMessage],
        deps=None,
        signals=None,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
        self.question = question
        self.knowledge = knowledge
        if signals is not None:
            signals.outcome = self._outcome
            signals.gate_retrieve = self._retrieve
            signals.gate_degraded = self._degraded
            signals.retrieval_ran = self._retrieve
            signals.retrieval_kept = self._retrieval_kept
            signals.tool_calls = self._tool_calls
            signals.input_tokens = self._input_tokens
            signals.output_tokens = self._output_tokens
            # Desde a revisão I2 quem mede a latência do motor é o grafo, não o
            # controller — o fake precisa preenchê-la como o runner real faz.
            # No caminho de recusa nenhum modelo roda: as duas ficam None.
            if self._outcome == "answer":
                signals.answer_started_at = 0.0
                signals.first_token_ms = self._first_token_ms
                signals.engine_ms = self._engine_ms
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentStreamChunk]:
        # Um passo "answer" em volta do texto, para os testes de integração
        # exercitarem a tradução de passos além de texto e fontes.
        yield StepChunk(name="answer", phase="started")
        for token in self._answer.split():
            yield TextChunk(text=token + " ")
        yield StepChunk(name="answer", phase="finished")
        cites = [] if self._outcome == "refusal" else self._citations
        yield SourcesChunk(citations=cites)
