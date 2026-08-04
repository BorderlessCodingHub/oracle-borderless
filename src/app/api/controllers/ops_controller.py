from uuid import UUID

from src.app.api.responses.ops_responses import (
    OpsOverviewResponse,
    TurnDetailResponse,
    TurnSummaryResponse,
    Window,
)
from src.domain.observability.actions.get_ops_overview_action import GetOpsOverviewAction
from src.domain.observability.actions.get_turn_trace_action import GetTurnTraceAction
from src.domain.observability.actions.list_recent_traces_action import ListRecentTracesAction
from src.domain.observability.actions.read_eval_report_action import ReadEvalReportAction


class OpsController:
    @staticmethod
    async def overview(window: Window = "24h") -> OpsOverviewResponse:
        return OpsOverviewResponse.from_dto(await GetOpsOverviewAction().execute(window))

    @staticmethod
    async def turns(window: Window = "24h", limit: int = 50) -> list[TurnSummaryResponse]:
        traces = await ListRecentTracesAction().execute(window=window, limit=limit)
        return [TurnSummaryResponse.from_entity(t) for t in traces]

    @staticmethod
    async def turn(trace_id: UUID) -> TurnDetailResponse:
        return TurnDetailResponse.from_entity(await GetTurnTraceAction().execute(trace_id))

    @staticmethod
    async def eval_report() -> dict:
        return await ReadEvalReportAction().execute()
