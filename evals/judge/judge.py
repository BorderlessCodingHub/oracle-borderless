"""Juiz de eval sobre Pydantic AI (hand-rolled, mesmo padrão do RetrievalGate).
Fora de src/ — pode importar pydantic_ai livremente."""

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from evals.judge.rubrics import JUDGE_SYSTEM_PROMPT, build_judge_prompt
from evals.models import (
    APPROPRIATE_REFUSAL,
    CITATION_SUPPORT,
    FAITHFULNESS,
    EvalCase,
    MetricScore,
    metrics_for_category,
)
from src.support.core.settings import settings


class MetricValue(BaseModel):
    score: float
    reason: str


class JudgeOutput(BaseModel):
    faithfulness: MetricValue | None = None
    citation_support: MetricValue | None = None
    appropriate_refusal: MetricValue | None = None


def _build_judge_model():
    if settings.LLM_PROVIDER == "openai":
        model_id = settings.JUDGE_MODEL or settings.OPENAI_MODEL
        return OpenAIChatModel(model_id, provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY))
    model_id = settings.JUDGE_MODEL or settings.ANTHROPIC_MODEL
    return AnthropicModel(model_id, provider=AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY))


def _build_judge_agent() -> Agent:
    return Agent(_build_judge_model(), system_prompt=JUDGE_SYSTEM_PROMPT, output_type=JudgeOutput)


class AnswerJudge:
    def __init__(self, agent=None) -> None:
        self._agent = agent or _build_judge_agent()

    async def score(self, case: EvalCase, sources_text: str, answer: str) -> dict[str, MetricScore]:
        metrics = metrics_for_category(case.category)
        prompt = build_judge_prompt(case.question, sources_text, answer, metrics)
        result = await self._agent.run(prompt)
        out = result.output
        field_map = {
            FAITHFULNESS: out.faithfulness,
            CITATION_SUPPORT: out.citation_support,
            APPROPRIATE_REFUSAL: out.appropriate_refusal,
        }
        scores: dict[str, MetricScore] = {}
        for metric in metrics:
            mv = field_map[metric]
            if mv is None:
                raise ValueError(f"judge did not return required metric {metric} for case {case.id}")
            scores[metric] = MetricScore(score=float(mv.score), reason=mv.reason)
        return scores


def get_answer_judge() -> "AnswerJudge":
    return AnswerJudge()
