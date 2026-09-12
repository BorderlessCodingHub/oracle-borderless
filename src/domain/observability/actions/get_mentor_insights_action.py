"""As duas leituras de produto do mentor (spec §9.3).

Backlog: perguntas que a aula não cobriu, pauta de gravação escrita por quem
assiste. Retenção: por aula, quantos alunos distintos perguntaram e quanto o
mentor citou — muitos turnos com POUCAS citações é aula confusa; muitos turnos
com MUITAS citações é aula sendo minerada de verdade.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import ColumnElement, case, func, select

from src.domain.observability.dtos.mentor_insights import (
    LessonEngagement,
    LessonGap,
    MentorInsights,
)
from src.domain.observability.models.turn_trace import TurnTraceModel
from src.support.core.context import CurrentAsyncSessionContext


def _scope(program_slug: str | None, since: datetime) -> list[ColumnElement]:
    """Filtro comum às duas queries: só turnos do mentor, dentro da janela, e
    — quando informado — de um programa específico. Fatorado à parte (em vez
    de inline no `execute`) para poder ser testado sem sessão: só monta
    condições SQLAlchemy, não toca em banco."""
    scope: list[ColumnElement] = [
        TurnTraceModel.intent == "mentor",
        TurnTraceModel.created_at >= since,
    ]
    if program_slug:
        scope.append(TurnTraceModel.program_slug == program_slug)
    return scope


def _gap_from_row(row) -> LessonGap:
    """Mapeamento puro linha → DTO — sem sessão, testável sem banco."""
    return LessonGap(
        lesson_id=row.lesson_id,
        program_slug=row.program_slug,
        question=row.question,
        asked_at=row.created_at.isoformat(),
        user_email=row.user_email,
    )


def _engagement_from_row(row) -> LessonEngagement:
    """Idem, para a linha agregada por aula. `turns == 0` nunca deveria
    acontecer (a linha só existe porque houve `GROUP BY` com pelo menos um
    turno), mas a guarda evita `ZeroDivisionError` se algum dia acontecer."""
    turns = int(row.turns)
    return LessonEngagement(
        lesson_id=row.lesson_id,
        turns=turns,
        distinct_users=int(row.users),
        avg_citations=float(row.avg_citations or 0.0),
        gap_ratio=(float(row.gaps or 0) / turns) if turns else 0.0,
    )


class GetMentorInsightsAction:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def execute(self, program_slug: str | None = None, days: int = 30) -> MentorInsights:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        scope = _scope(program_slug, since)

        gaps_rows = (
            await self.session.execute(
                select(
                    TurnTraceModel.lesson_id,
                    TurnTraceModel.program_slug,
                    TurnTraceModel.question,
                    TurnTraceModel.created_at,
                    TurnTraceModel.user_email,
                )
                .where(*scope, TurnTraceModel.lesson_coverage == "gap")
                .order_by(TurnTraceModel.created_at.desc())
                .limit(500)
            )
        ).all()

        gap_flag = func.sum(case((TurnTraceModel.lesson_coverage == "gap", 1), else_=0))
        engagement_rows = (
            await self.session.execute(
                select(
                    TurnTraceModel.lesson_id,
                    func.count().label("turns"),
                    func.count(func.distinct(TurnTraceModel.user_email)).label("users"),
                    func.avg(TurnTraceModel.citations_count).label("avg_citations"),
                    gap_flag.label("gaps"),
                )
                .where(*scope)
                .group_by(TurnTraceModel.lesson_id)
                .order_by(func.count().desc())
            )
        ).all()

        return MentorInsights(
            gaps=[_gap_from_row(r) for r in gaps_rows],
            engagement=[_engagement_from_row(r) for r in engagement_rows],
        )
