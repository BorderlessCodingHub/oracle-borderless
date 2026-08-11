from uuid import UUID

from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository
from src.support.core.exceptions import NotFoundError


class GetTurnTraceAction:
    """Detalhe de um turno — o que a página de ops mostra ao abrir um trace."""

    def __init__(self, traces=None) -> None:
        self.traces = traces or TurnTraceRepository()

    async def execute(self, trace_id: UUID) -> TurnTrace:
        trace = await self.traces.get(trace_id)
        if trace is None:
            raise NotFoundError(f"trace {trace_id} não encontrado")
        return trace
