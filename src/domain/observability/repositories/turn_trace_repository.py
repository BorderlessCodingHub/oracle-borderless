from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Float, case, func, select
from sqlalchemy.sql.elements import ColumnElement

from src.domain.observability.dtos.ops_overview import TraceSummary
from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.mappers import TurnTraceMapper
from src.domain.observability.models.turn_trace import TurnTraceModel
from src.support.core.context import CurrentAsyncSessionContext

_WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "all": None}


def _window_start(window: str) -> datetime | None:
    if window not in _WINDOWS:
        raise ValueError(f"janela inválida: {window!r}")
    delta = _WINDOWS[window]
    return None if delta is None else datetime.now(timezone.utc) - delta


class TurnTraceRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def append(self, trace: TurnTrace) -> TurnTrace:
        model = TurnTraceModel(**TurnTraceMapper.to_model_attrs(trace))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return TurnTraceMapper.to_entity(model)

    def _in_window(self, window: str) -> list[ColumnElement]:
        start = _window_start(window)
        return [] if start is None else [TurnTraceModel.created_at >= start]

    async def summarize(self, window: str) -> TraceSummary:
        """Agregados da janela numa única query com `GROUP BY`/funções agregadas.

        `func.avg`/`func.max` do SQL ignoram NULL — comportamento desejado, já
        que `engine_ms`/`first_token_ms` ficam NULL no caminho de recusa
        determinística (Task 5) e não devem puxar a média para baixo.
        """

        def count_when(condition) -> ColumnElement:
            return func.count(case((condition, 1)))

        stmt = select(
            func.count().label("turns"),
            count_when(TurnTraceModel.gate_retrieve.is_(True)).label("gate_retrieve"),
            count_when(TurnTraceModel.gate_retrieve.is_(False)).label("gate_skip"),
            count_when(TurnTraceModel.gate_degraded.is_(True)).label("gate_degraded"),
            count_when(TurnTraceModel.outcome == "answer").label("answers"),
            count_when(TurnTraceModel.outcome == "refusal").label("refusals"),
            count_when(TurnTraceModel.outcome == "error").label("errors"),
            func.avg(TurnTraceModel.first_token_ms.cast(Float)).label("avg_first_token_ms"),
            func.max(TurnTraceModel.first_token_ms).label("max_first_token_ms"),
            func.avg(TurnTraceModel.engine_ms.cast(Float)).label("avg_engine_ms"),
            func.max(TurnTraceModel.engine_ms).label("max_engine_ms"),
            func.avg(TurnTraceModel.retrieval_kept.cast(Float)).label("avg_retrieval_kept"),
            func.avg(TurnTraceModel.retrieval_best_distance).label("avg_best_distance"),
        ).where(*self._in_window(window))

        row = (await self.session.execute(stmt)).one()
        return TraceSummary(
            turns=row.turns,
            gate_retrieve=row.gate_retrieve,
            gate_skip=row.gate_skip,
            gate_degraded=row.gate_degraded,
            answers=row.answers,
            refusals=row.refusals,
            errors=row.errors,
            avg_first_token_ms=float(row.avg_first_token_ms) if row.avg_first_token_ms is not None else None,
            max_first_token_ms=row.max_first_token_ms,
            avg_engine_ms=float(row.avg_engine_ms) if row.avg_engine_ms is not None else None,
            max_engine_ms=row.max_engine_ms,
            avg_retrieval_kept=float(row.avg_retrieval_kept) if row.avg_retrieval_kept is not None else None,
            avg_best_distance=float(row.avg_best_distance) if row.avg_best_distance is not None else None,
        )

    async def list_recent(self, window: str, limit: int = 50) -> list[TurnTrace]:
        stmt = (
            select(TurnTraceModel)
            .where(*self._in_window(window))
            .order_by(TurnTraceModel.created_at.desc())
            .limit(limit)
        )
        models = (await self.session.execute(stmt)).scalars().all()
        return [TurnTraceMapper.to_entity(m) for m in models]

    async def get(self, trace_id: UUID) -> TurnTrace | None:
        stmt = select(TurnTraceModel).where(TurnTraceModel.uuid == trace_id)
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return TurnTraceMapper.to_entity(model) if model else None
