"""Seleção de ChatModel por LLM_PROVIDER. Ponto ÚNICO — antes isto estava
duplicado entre o motor e o gate.

As chaves vêm de `settings`, não de `os.environ`: os provedores do LangChain
leriam o ambiente por conta própria, e neste projeto as chaves vivem no .env
sem serem exportadas (mesmo motivo do OpenAIEmbeddingsClient).
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from src.support.core.settings import settings


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} não configurada — necessária para LLM_PROVIDER={settings.LLM_PROVIDER}")
    return value


def _build(anthropic_model: str, openai_model: str) -> BaseChatModel:
    if settings.LLM_PROVIDER == "openai":
        return ChatOpenAI(
            model=openai_model,
            api_key=_require(settings.OPENAI_API_KEY, "OPENAI_API_KEY"),
        )
    return ChatAnthropic(
        model=anthropic_model,
        api_key=_require(settings.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY"),
    )


def build_chat_model() -> BaseChatModel:
    """Modelo grande — responde ao usuário."""
    return _build(settings.ANTHROPIC_MODEL, settings.OPENAI_MODEL)


def build_small_model() -> BaseChatModel:
    """Modelo pequeno — só o retrieval gate."""
    return _build(settings.ANTHROPIC_SMALL_MODEL, settings.OPENAI_SMALL_MODEL)
