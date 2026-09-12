"""`_gap_from_row`/`_engagement_from_row` são a parte pura da Action — mapeiam
uma linha de query (qualquer objeto com os atributos certos, aqui um
`SimpleNamespace`) para os DTOs, sem sessão nem banco. A aritmética de
`gap_ratio`/`avg_citations` mora aqui porque é a parte que vale a pena testar
sem PostgreSQL. `_scope` é o outro pedaço puro: monta as condições SQLAlchemy
compartilhadas pelas duas queries — testável compilando o SQL, sem sessão."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from src.domain.observability.actions.get_mentor_insights_action import (
    _engagement_from_row,
    _gap_from_row,
    _scope,
)
from src.domain.observability.dtos.mentor_insights import LessonEngagement, LessonGap
from src.domain.observability.models.turn_trace import TurnTraceModel


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _gap_row(**overrides):
    defaults = dict(
        lesson_id="v1",
        program_slug="base",
        question="o que é autorregressão?",
        created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        user_email="aluno@x.com",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _engagement_row(**overrides):
    defaults = dict(lesson_id="v1", turns=3, users=2, avg_citations=2.0, gaps=1)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_gap_from_row_maps_fields_and_formats_the_timestamp():
    gap = _gap_from_row(_gap_row())

    assert gap == LessonGap(
        lesson_id="v1",
        program_slug="base",
        question="o que é autorregressão?",
        asked_at="2026-01-01T12:00:00+00:00",
        user_email="aluno@x.com",
    )


def test_engagement_from_row_computes_gap_ratio_and_casts_counts():
    row = _engagement_row(turns=3, users=2, avg_citations=2.0, gaps=1)

    engagement = _engagement_from_row(row)

    assert engagement == LessonEngagement(
        lesson_id="v1", turns=3, distinct_users=2, avg_citations=2.0, gap_ratio=pytest.approx(1 / 3)
    )


def test_engagement_from_row_guards_division_by_zero_when_there_are_no_turns():
    row = _engagement_row(turns=0, users=0, avg_citations=None, gaps=0)

    engagement = _engagement_from_row(row)

    assert engagement.gap_ratio == 0.0


def test_engagement_from_row_defaults_a_null_average_to_zero():
    row = _engagement_row(avg_citations=None)

    engagement = _engagement_from_row(row)

    assert engagement.avg_citations == 0.0


def test_engagement_from_row_defaults_null_gap_count_to_zero():
    row = _engagement_row(turns=4, gaps=None)

    engagement = _engagement_from_row(row)

    assert engagement.gap_ratio == 0.0


def test_scope_filters_by_program_slug_only_when_given():
    """Regressão: o teste de integração do brief passa `program_slug="base"`
    sem nenhuma linha semeada declarar esse campo (o default vem do fixture
    `seed_trace`). Isso só prova a filtragem funciona se o filtro realmente
    existir no SQL — este teste checa isso direto, sem depender do fixture."""
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with_program = _compiled(select(TurnTraceModel).where(*_scope("base", since)))
    without_program = _compiled(select(TurnTraceModel).where(*_scope(None, since)))

    assert "program_slug = 'base'" in with_program
    # `select(TurnTraceModel)` sempre lista a coluna `program_slug` (é um
    # campo do model) — o que não pode aparecer é a CONDIÇÃO de igualdade.
    assert "program_slug =" not in without_program
    # Ambas sempre trazem o filtro de intent + janela.
    for sql in (with_program, without_program):
        assert "intent = 'mentor'" in sql
        assert "created_at >=" in sql


def test_scope_with_a_different_program_slug_excludes_the_other():
    """`program_slug="outro"` não deveria casar com linhas de `"base"` — o
    filtro é uma igualdade estrita, não um "contém"."""
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    sql = _compiled(select(TurnTraceModel).where(*_scope("outro", since)))

    assert "program_slug = 'outro'" in sql
    assert "program_slug = 'base'" not in sql
