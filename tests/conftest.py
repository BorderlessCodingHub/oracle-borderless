"""Configuração global de testes."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Configura variáveis de ambiente para testes."""
    # Dummy API key para testes unitários — não faz chamadas reais.
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy-key"
    if not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-dummy-key"

    # JWT de teste (ADR-0017): HS256 com segredo fixo, forjado por tests/fakes/auth.py
    from src.support.core.settings import settings
    from tests.fakes.auth import TEST_JWT_ALGORITHM, TEST_JWT_SECRET

    settings.BORDERLESS_JWT_ALGORITHM = TEST_JWT_ALGORITHM
    settings.BORDERLESS_JWT_VERIFY_KEY = TEST_JWT_SECRET
