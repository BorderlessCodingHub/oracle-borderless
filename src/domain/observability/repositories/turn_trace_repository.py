from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.mappers import TurnTraceMapper
from src.domain.observability.models.turn_trace import TurnTraceModel
from src.support.core.context import CurrentAsyncSessionContext


class TurnTraceRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def append(self, trace: TurnTrace) -> TurnTrace:
        model = TurnTraceModel(**TurnTraceMapper.to_model_attrs(trace))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return TurnTraceMapper.to_entity(model)
