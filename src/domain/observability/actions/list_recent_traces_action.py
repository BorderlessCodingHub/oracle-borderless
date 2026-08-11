from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


class ListRecentTracesAction:
    """Lista de turnos recentes numa janela — a lista que a página de ops exibe."""

    def __init__(self, traces=None) -> None:
        self.traces = traces or TurnTraceRepository()

    async def execute(self, window: str, limit: int = 50) -> list[TurnTrace]:
        return await self.traces.list_recent(window=window, limit=limit)
