from uuid import UUID

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


class RecordTurnTraceAction:
    """Persiste o trace do turno. Chamada dentro de run_in_async_session,
    junto da resposta do assistente — uma sessão, duas escritas."""

    def __init__(self) -> None:
        self.traces = TurnTraceRepository()

    async def execute(self, conversation_id: UUID, draft: TurnTraceDraft) -> None:
        await self.traces.append(draft.to_entity(conversation_id=conversation_id))
