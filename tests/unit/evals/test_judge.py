import pytest

from evals.judge.judge import AnswerJudge, JudgeOutput, MetricValue
from evals.models import (
    APPROPRIATE_REFUSAL,
    CITATION_SUPPORT,
    FAITHFULNESS,
    EvalCase,
)


class _Result:
    def __init__(self, output):
        self.output = output


class _StubAgent:
    def __init__(self, output):
        self._output = output
        self.prompt = None

    async def run(self, prompt):
        self.prompt = prompt
        return _Result(self._output)


@pytest.mark.asyncio
async def test_scores_only_applicable_metrics_for_answerable():
    out = JudgeOutput(
        faithfulness=MetricValue(score=0.9, reason="grounded"),
        citation_support=MetricValue(score=0.8, reason="cited"),
        appropriate_refusal=MetricValue(score=0.1, reason="n/a"),
    )
    judge = AnswerJudge(agent=_StubAgent(out))
    case = EvalCase(id="a", category="answerable", question="q")

    scores = await judge.score(case, "sources", "answer")

    assert set(scores) == {FAITHFULNESS, CITATION_SUPPORT}
    assert scores[FAITHFULNESS].score == 0.9
    assert scores[CITATION_SUPPORT].reason == "cited"


@pytest.mark.asyncio
async def test_scores_only_refusal_metric_for_refusal_case():
    out = JudgeOutput(appropriate_refusal=MetricValue(score=1.0, reason="refused"))
    judge = AnswerJudge(agent=_StubAgent(out))
    case = EvalCase(id="r", category="refusal", question="q", should_refuse=True)

    scores = await judge.score(case, "sources", "não está na base")

    assert set(scores) == {APPROPRIATE_REFUSAL}
    assert scores[APPROPRIATE_REFUSAL].score == 1.0


@pytest.mark.asyncio
async def test_raises_when_judge_omits_a_required_metric():
    out = JudgeOutput(faithfulness=MetricValue(score=0.9, reason="ok"))  # citation missing
    judge = AnswerJudge(agent=_StubAgent(out))
    case = EvalCase(id="a", category="answerable", question="q")

    with pytest.raises(ValueError, match="citation_support"):
        await judge.score(case, "sources", "answer")


@pytest.mark.asyncio
async def test_prompt_includes_answer_and_sources():
    out = JudgeOutput(faithfulness=MetricValue(score=0.9, reason="ok"))
    agent = _StubAgent(out)
    judge = AnswerJudge(agent=agent)
    case = EvalCase(id="adv", category="adversarial", question="q", poisoned_context="P")

    await judge.score(case, "SOURCES-TEXT", "ANSWER-TEXT")

    assert "SOURCES-TEXT" in agent.prompt
    assert "ANSWER-TEXT" in agent.prompt
