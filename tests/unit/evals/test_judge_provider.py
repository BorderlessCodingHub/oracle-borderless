"""O juiz fala com a OpenAI pelo SDK direto — sem framework de agente."""

import pytest

from evals.judge.judge import AnswerJudge, JudgeOutput, MetricValue, _build_client
from evals.models import EvalCase
from src.support.core.settings import settings


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


@pytest.mark.asyncio
async def test_score_calls_parse_with_the_configured_judge_model():
    """O juiz precisa usar o tier configurado em JUDGE_MODEL, não um default
    implícito do SDK — senão uma troca silenciosa de settings muda o
    comportamento do eval sem que nenhum teste perceba."""
    client = _FakeClient(JudgeOutput(faithfulness=MetricValue(score=1.0, reason="ok")))
    judge = AnswerJudge(client=client)
    case = EvalCase(id="c3", category="adversarial", question="q")

    await judge.score(case, "fonte", "resposta")

    assert client.completions.kwargs["model"] == settings.JUDGE_MODEL


def test_build_client_uses_the_openai_key_even_with_anthropic_as_the_oracle_provider(monkeypatch):
    """O juiz é sempre OpenAI, independente de LLM_PROVIDER (spec de
    2026-08-03, seção 7) — não há camada multi-provedor aqui de propósito.
    Mesmo com o oráculo em Anthropic, o client do juiz usa OPENAI_API_KEY."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-guardrail")

    client = _build_client()

    assert client.api_key == settings.OPENAI_API_KEY


def test_judge_model_default_is_not_the_gate_tier():
    """Descer ao tier do gate (OPENAI_SMALL_MODEL) arrisca a métrica que
    sustenta o produto — guardrail barato contra regressão de config."""
    assert settings.JUDGE_MODEL != settings.OPENAI_SMALL_MODEL
