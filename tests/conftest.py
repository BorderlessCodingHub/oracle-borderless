"""Configuração global de testes."""

import asyncio
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

    yield

    # Sessões semeadas por tests/fakes/auth.py (ADR-0018) não podem acumular
    # no banco de dev entre execuções.
    from tests.fakes.auth import purge_seeded_sessions

    asyncio.run(purge_seeded_sessions())
