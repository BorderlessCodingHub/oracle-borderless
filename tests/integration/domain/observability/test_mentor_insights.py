"""As duas leituras de produto do mentor: backlog (gaps) e retenção
(engagement). `seed_trace` (singular, kwargs soltos) é o complemento de
`seed_traces` definido em `tests/integration/conftest.py` — cada chamada é uma
pergunta. `program_slug` default do fixture é "base", por isso o primeiro
teste filtra por `program_slug="base"` sem precisar declará-lo em cada seed."""

import pytest

from src.domain.observability.actions.get_mentor_insights_action import GetMentorInsightsAction


@pytest.mark.asyncio
async def test_only_gap_questions_reach_the_backlog(db_session, seed_trace):
    await seed_trace(intent="mentor", lesson_id="v1", lesson_coverage="gap", question="o que é autorregressão?")
    await seed_trace(intent="mentor", lesson_id="v1", lesson_coverage="covered", question="o que são tokens?")

    insights = await GetMentorInsightsAction().execute(program_slug="base")

    assert [g.question for g in insights.gaps] == ["o que é autorregressão?"]


@pytest.mark.asyncio
async def test_non_mentor_turns_never_pollute_the_reading(db_session, seed_trace):
    await seed_trace(intent="navigate", lesson_id=None, lesson_coverage=None, question="me leva pras trilhas")

    insights = await GetMentorInsightsAction().execute()

    assert insights.gaps == []
    assert insights.engagement == []


@pytest.mark.asyncio
async def test_engagement_counts_distinct_students_not_turns(db_session, seed_trace):
    await seed_trace(intent="mentor", lesson_id="v1", lesson_coverage="covered", user_email="a@x.com", citations_count=2)
    await seed_trace(intent="mentor", lesson_id="v1", lesson_coverage="covered", user_email="a@x.com", citations_count=4)
    await seed_trace(intent="mentor", lesson_id="v1", lesson_coverage="gap", user_email="b@x.com", citations_count=0)

    row = (await GetMentorInsightsAction().execute()).engagement[0]

    assert row.turns == 3
    assert row.distinct_users == 2
    assert row.avg_citations == pytest.approx(2.0)
    assert row.gap_ratio == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_program_slug_excludes_rows_from_a_different_program(db_session, seed_trace):
    """Achado da revisão: nenhum teste anterior provava que o filtro
    `program_slug` EXCLUI algo — `test_only_gap_questions_reach_the_backlog`
    passa mesmo se o filtro for ignorado, porque o default do fixture já é
    "base". Aqui as duas linhas divergem de propósito."""
    await seed_trace(
        intent="mentor", lesson_id="v1", lesson_coverage="gap",
        question="pergunta do programa base", program_slug="base",
    )
    await seed_trace(
        intent="mentor", lesson_id="v1", lesson_coverage="gap",
        question="pergunta de outro programa", program_slug="outro",
    )

    scoped = await GetMentorInsightsAction().execute(program_slug="base")
    assert [g.question for g in scoped.gaps] == ["pergunta do programa base"]

    unscoped = await GetMentorInsightsAction().execute()
    assert {g.question for g in unscoped.gaps} == {
        "pergunta do programa base",
        "pergunta de outro programa",
    }
