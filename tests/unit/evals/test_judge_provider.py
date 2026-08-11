"""O juiz é OpenAI mesmo quando o oráculo é Claude (spec 2026-08-03, seção 7).

Razões trancadas por este teste: menos viés de auto-preferência (as respostas
são geradas por Claude) e a chave da OpenAI já é obrigatória para embeddings.
"""

from pydantic_ai.models.openai import OpenAIChatModel

from evals.judge.judge import _build_judge_model
from src.support.core.settings import settings


def test_uses_openai_even_with_anthropic_as_the_oracle_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    assert isinstance(_build_judge_model(), OpenAIChatModel)


def test_judge_model_default_is_not_the_gate_tier():
    """Descer ao tier do gate arrisca a métrica que sustenta o produto."""
    assert settings.JUDGE_MODEL != settings.OPENAI_SMALL_MODEL
    assert settings.JUDGE_MODEL == "gpt-4.1-mini"


def test_judge_model_is_never_none():
    assert isinstance(settings.JUDGE_MODEL, str) and settings.JUDGE_MODEL
