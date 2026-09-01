"""A seleção de provedor é um ponto único e lê a chave de settings, nunca do
ambiente — os provedores do LangChain leriam os.environ se deixássemos."""

import pytest

from src.support.agent.models import build_chat_model, build_small_model
from src.support.core.settings import settings


@pytest.fixture
def anthropic(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture
def openai(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-oai-test")


def test_big_model_follows_the_anthropic_provider(anthropic):
    model = build_chat_model()
    assert model.model == settings.ANTHROPIC_MODEL


def test_small_model_follows_the_anthropic_provider(anthropic):
    model = build_small_model()
    assert model.model == settings.ANTHROPIC_SMALL_MODEL


def test_big_model_follows_the_openai_provider(openai):
    model = build_chat_model()
    assert model.model_name == settings.OPENAI_MODEL


def test_small_model_follows_the_openai_provider(openai):
    model = build_small_model()
    assert model.model_name == settings.OPENAI_SMALL_MODEL


def test_an_unset_key_fails_loudly_instead_of_reading_the_environment(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_chat_model()
