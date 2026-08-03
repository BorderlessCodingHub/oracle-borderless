"""Motor fake — implementa OracleEnginePort sem chamar LLM."""

from typing import AsyncIterator

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, AgentStreamChunk, KnowledgeSnippet


class FakeOracleEngine:
    def __init__(self, answer: str = "resposta", citations: list[Citation] | None = None) -> None:
        self._answer = answer
        self._citations = citations or [Citation("notion", "Doc", "https://n/a", "trecho", "a")]

    async def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet] | None = None,
        metrics=None,
    ) -> AsyncIterator[AgentStreamChunk]:
        for token in self._answer.split():
            yield AgentStreamChunk(type="text", text=token + " ")
        cites = [s.citation for s in (knowledge or [])] or self._citations
        yield AgentStreamChunk(type="sources", citations=cites)
