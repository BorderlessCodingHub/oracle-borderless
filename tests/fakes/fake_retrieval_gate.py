"""Gate fake — implementa RetrievalGatePort sem chamar LLM."""

from src.support.agent.ports import AgentMessage, RetrievalDecision


class FakeRetrievalGate:
    def __init__(
        self,
        retrieve: bool = True,
        search_query: str | None = None,
        degraded: bool = False,
    ) -> None:
        self._retrieve = retrieve
        self._search_query = search_query
        self._degraded = degraded
        self.received: tuple[str, list[AgentMessage]] | None = None

    async def decide(self, question: str, history: list[AgentMessage]) -> RetrievalDecision:
        self.received = (question, history)
        if not self._retrieve:
            return RetrievalDecision(retrieve=False, search_query="")
        query = self._search_query if self._search_query is not None else question
        return RetrievalDecision(retrieve=True, search_query=query, degraded=self._degraded)
