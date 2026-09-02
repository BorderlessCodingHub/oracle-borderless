"""Juiz de eval sobre o SDK da OpenAI. Sempre OpenAI, independente de
LLM_PROVIDER (spec de 2026-08-03, seção 7) — então não há camada
multi-provedor aqui de propósito."""

from openai import AsyncOpenAI
from pydantic import BaseModel

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


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


class AnswerJudge:
    def __init__(self, client=None) -> None:
        self._client = client or _build_client()

    async def score(self, case: EvalCase, sources_text: str, answer: str) -> dict[str, MetricScore]:
        metrics = metrics_for_category(case.category)
        prompt = build_judge_prompt(
            case.question, sources_text, answer, metrics, category=case.category
        )
        response = await self._client.beta.chat.completions.parse(
            model=settings.JUDGE_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format=JudgeOutput,
        )
        out = response.choices[0].message.parsed
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
