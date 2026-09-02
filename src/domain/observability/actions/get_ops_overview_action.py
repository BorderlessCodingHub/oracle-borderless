from sqlalchemy import select

from src.domain.documents.actions.count_knowledge_base_action import CountKnowledgeBaseAction
from src.domain.observability.dtos.ops_overview import OpsOverview, SyncStatus
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.models.job_execution import JobExecution
from src.support.core.settings import settings


class GetOpsOverviewAction:
    """Tudo que o mapa vivo precisa, numa chamada."""

    def __init__(self, counts=None, traces=None) -> None:
        self.counts = counts or CountKnowledgeBaseAction()
        self.traces = traces or TurnTraceRepository()
        self.session = CurrentAsyncSessionContext.get()

    async def execute(self, window: str) -> OpsOverview:
        return OpsOverview(
            window=window,
            knowledge=await self.counts.execute(),
            sync=await self._last_sync(),
            traces=await self.traces.summarize(window),
            rag_top_k=settings.RAG_TOP_K,
            rag_max_distance=settings.RAG_MAX_DISTANCE,
            knowledge_gaps=await self.traces.knowledge_gaps(window),
        )

    async def _last_sync(self) -> SyncStatus:
        stmt = (
            select(JobExecution)
            .where(JobExecution.job_name.ilike("%SyncKnowledgeBase%"))
            .order_by(JobExecution.started_at.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return SyncStatus()
        return SyncStatus(
            job_name=row.job_name,
            status=row.status,
            started_at=row.started_at.isoformat() if row.started_at else None,
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
            error=row.error,
        )
