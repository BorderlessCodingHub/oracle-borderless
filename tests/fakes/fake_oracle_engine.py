"""Motor fake — implementa OracleEnginePort sem chamar LLM."""

from typing import AsyncIterator

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, AgentStreamChunk, KnowledgeSnippet


class FakeOracleEngine:
    def __init__(
        self,
        answer: str = "resposta",
        citations: list[Citation] | None = None,
        tool_calls: int = 0,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self._answer = answer
        self._citations = citations or [Citation("notion", "Doc", "https://n/a", "trecho", "a")]
        # Espelha o que o motor real preenche em `metrics` (Task 5): permite
        # testes de integração afirmarem que a cadeia engine → draft → coluna
        # do trace está de fato conectada, não só que o caminho feliz roda.
        self._tool_calls = tool_calls
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet] | None = None,
        metrics=None,
    ) -> AsyncIterator[AgentStreamChunk]:
        for token in self._answer.split():
            yield AgentStreamChunk(type="text", text=token + " ")
        if metrics is not None:
            metrics.tool_calls = self._tool_calls
            metrics.input_tokens = self._input_tokens
            metrics.output_tokens = self._output_tokens
        cites = [s.citation for s in (knowledge or [])] or self._citations
        yield AgentStreamChunk(type="sources", citations=cites)
