import pytest

from evals.judge.judge import AnswerJudge, JudgeOutput, MetricValue
from evals.models import (
    APPROPRIATE_REFUSAL,
    CITATION_SUPPORT,
    FAITHFULNESS,
    EvalCase,
)


class _FakeCompletions:
    def __init__(self, parsed):
        self._parsed = parsed
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        message = type("_Msg", (), {"parsed": self._parsed})()
        choice = type("_Choice", (), {"message": message})()
        return type("_Resp", (), {"choices": [choice]})()


class _FakeClient:
    def __init__(self, parsed):
        self.completions = _FakeCompletions(parsed)
        self.beta = type("_Beta", (), {"chat": self})()
        self.chat = self

    @property
    def prompt(self):
        if self.completions.kwargs is None:
            return None
        return self.completions.kwargs["messages"][1]["content"]


@pytest.mark.asyncio
async def test_scores_only_applicable_metrics_for_answerable():
    out = JudgeOutput(
        faithfulness=MetricValue(score=0.9, reason="grounded"),
        citation_support=MetricValue(score=0.8, reason="cited"),
        appropriate_refusal=MetricValue(score=0.1, reason="n/a"),
    )
    judge = AnswerJudge(client=_FakeClient(out))
    case = EvalCase(id="a", category="answerable", question="q")

    scores = await judge.score(case, "sources", "answer")

    assert set(scores) == {FAITHFULNESS, CITATION_SUPPORT}
    assert scores[FAITHFULNESS].score == 0.9
    assert scores[CITATION_SUPPORT].reason == "cited"


@pytest.mark.asyncio
async def test_scores_only_refusal_metric_for_refusal_case():
    out = JudgeOutput(appropriate_refusal=MetricValue(score=1.0, reason="refused"))
    judge = AnswerJudge(client=_FakeClient(out))
    case = EvalCase(id="r", category="refusal", question="q", should_refuse=True)

    scores = await judge.score(case, "sources", "não está na base")

    assert set(scores) == {APPROPRIATE_REFUSAL}
    assert scores[APPROPRIATE_REFUSAL].score == 1.0


@pytest.mark.asyncio
async def test_raises_when_judge_omits_a_required_metric():
    out = JudgeOutput(faithfulness=MetricValue(score=0.9, reason="ok"))  # citation missing
    judge = AnswerJudge(client=_FakeClient(out))
    case = EvalCase(id="a", category="answerable", question="q")

    with pytest.raises(ValueError, match="citation_support"):
        await judge.score(case, "sources", "answer")


@pytest.mark.asyncio
async def test_prompt_includes_answer_and_sources():
    out = JudgeOutput(faithfulness=MetricValue(score=0.9, reason="ok"))
    client = _FakeClient(out)
    judge = AnswerJudge(client=client)
    case = EvalCase(id="adv", category="adversarial", question="q", poisoned_context="P")

    await judge.score(case, "SOURCES-TEXT", "ANSWER-TEXT")

    assert "SOURCES-TEXT" in client.prompt
    assert "ANSWER-TEXT" in client.prompt
