"""O juiz fala com a OpenAI pelo SDK direto — sem framework de agente."""

import pytest

from evals.judge.judge import AnswerJudge, JudgeOutput, MetricValue
from evals.models import EvalCase


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


@pytest.mark.asyncio
async def test_scores_an_answerable_case_from_the_parsed_output():
    parsed = JudgeOutput(
        faithfulness=MetricValue(score=0.9, reason="fiel ao contexto"),
        citation_support=MetricValue(score=0.8, reason="citou a fonte"),
    )
    client = _FakeClient(parsed)
    judge = AnswerJudge(client=client)
    case = EvalCase(id="c1", category="answerable", question="o que é PSP?")

    scores = await judge.score(case, "fonte", "resposta")

    assert scores["faithfulness"].score == 0.9
    assert scores["citation_support"].score == 0.8
    assert client.completions.kwargs["response_format"] is JudgeOutput


@pytest.mark.asyncio
async def test_raises_when_the_judge_omits_a_required_metric():
    client = _FakeClient(JudgeOutput(faithfulness=None, citation_support=None))
    judge = AnswerJudge(client=client)
    case = EvalCase(id="c2", category="answerable", question="q")

    with pytest.raises(ValueError, match="did not return required metric"):
        await judge.score(case, "fonte", "resposta")


def test_the_judge_module_does_not_import_pydantic_ai():
    import inspect

    import evals.judge.judge as mod

    assert "pydantic_ai" not in inspect.getsource(mod)
