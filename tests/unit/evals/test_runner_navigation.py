"""Métrica `navigation_target`: determinística, sem juiz.

O caso navega ou não navega, e o destino resolvido bate ou não bate com o
esperado — nada aqui depende de um LLM. Um `expected_destination` nulo é a
afirmação oposta: o turno NÃO pode navegar (pergunta ambígua).
"""

import pytest

from evals.models import NAVIGATION_TARGET, EvalCase
from evals.runner import run_case
from src.domain.conversations.services.out_of_scope_reply import (
    OUT_OF_SCOPE_OPENING_PT,
    build_out_of_scope_reply,
)
from tests.fakes.fake_turn_graph import FakeTurnGraph


def _navigation(destination_id: str) -> dict:
    return {
        "destination": {"id": destination_id, "path": f"/{destination_id}", "labelKey": f"navigation.destinations.{destination_id}"},
        "access": "allowed",
        "unlock": None,
        "signals": {"matchedTags": ["algorithms"]},
        "alternatives": [],
    }


class _NeverJudge:
    """O juiz não pode ser chamado para a categoria `navigation`."""

    def __init__(self) -> None:
        self.calls = 0

    async def score(self, case, sources_text, answer):
        self.calls += 1
        raise AssertionError("o juiz não deve ser chamado em casos de navegação")


class _NeverSearch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, query, top_k=None):
        self.calls.append(query)
        return []


def _case(cid: str, question: str, expected: str | None, mode: str = "navigate") -> EvalCase:
    return EvalCase(id=cid, category="navigation", question=question, expected_destination=expected, mode=mode)


@pytest.mark.asyncio
async def test_scores_one_when_destination_matches():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="Te levei para os desafios.", navigation=_navigation("code_breakers"))

    result = await run_case(_case("n1", "quero praticar algoritmos", "code_breakers"), graph=graph, search=search, judge=judge)

    assert set(result.scores) == {NAVIGATION_TARGET}
    assert result.scores[NAVIGATION_TARGET].score == 1.0
    assert "code_breakers" in result.scores[NAVIGATION_TARGET].reason
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_scores_zero_when_destination_is_the_wrong_one():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="Te levei para o fórum.", navigation=_navigation("forum"))

    result = await run_case(_case("n2", "quero praticar algoritmos", "code_breakers"), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 0.0
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_scores_zero_when_the_turn_did_not_navigate_at_all():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="Posso te ajudar com isso.", navigation=None)

    result = await run_case(_case("n3", "quero praticar algoritmos", "code_breakers"), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 0.0
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_null_destination_scores_one_when_nothing_was_navigated():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="Melhorar em quê? Algoritmos, entrevistas ou trilhas?", navigation=None)

    result = await run_case(_case("n4", "quero melhorar", None), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 1.0
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_null_destination_scores_zero_when_the_turn_navigated_anyway():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="Te levei para as trilhas.", navigation=_navigation("trails"))

    result = await run_case(_case("n5", "quero melhorar", None), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 0.0
    assert judge.calls == 0


@pytest.mark.asyncio
async def test_refusal_opening_zeroes_the_case_even_with_the_right_destination():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer=OUT_OF_SCOPE_OPENING_PT, navigation=_navigation("code_breakers"))

    result = await run_case(_case("n6", "quero praticar algoritmos", "code_breakers"), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 0.0
    assert "recusa" in result.scores[NAVIGATION_TARGET].reason


@pytest.mark.asyncio
async def test_refusal_opening_zeroes_the_null_case_too():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer=OUT_OF_SCOPE_OPENING_PT, navigation=None)

    result = await run_case(_case("n7", "quero melhorar", None), graph=graph, search=search, judge=judge)

    assert result.scores[NAVIGATION_TARGET].score == 0.0


@pytest.mark.asyncio
async def test_mode_and_extra_config_reach_the_graph():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="ok", navigation=_navigation("leaderboard"))
    extra = {"platform_token": "eval", "navigation_client": object()}

    await run_case(
        _case("n8", "how do I get to the leaderboard?", "leaderboard", mode="chat"),
        graph=graph, search=search, judge=judge, extra_config=extra,
    )

    assert graph.received_mode == "chat"
    assert graph.received_extra_config is extra
    assert search.calls == []  # navegação não recompõe fontes: não há juiz para ver


@pytest.mark.asyncio
async def test_bar_mode_case_runs_the_graph_in_navigate_mode():
    judge, search = _NeverJudge(), _NeverSearch()
    graph = FakeTurnGraph(answer="ok", navigation=_navigation("events"))

    await run_case(_case("n9", "onde vejo meus eventos?", "events"), graph=graph, search=search, judge=judge)

    assert graph.received_mode == "navigate"


@pytest.mark.asyncio
async def test_refusal_in_english_also_zeroes_a_null_case():
    """A recusa sai no idioma da pergunta; a métrica precisa reconhecer as duas."""
    judge, search = _NeverJudge(), _NeverSearch()
    english_refusal = build_out_of_scope_reply([], "how do I get to the leaderboard?")
    graph = FakeTurnGraph(answer=english_refusal, navigation=None)

    result = await run_case(
        _case("n10", "how do I get to the leaderboard?", None, mode="chat"),
        graph=graph, search=search, judge=judge,
    )

    assert result.scores[NAVIGATION_TARGET].score == 0.0
    assert "recusa" in result.scores[NAVIGATION_TARGET].reason
