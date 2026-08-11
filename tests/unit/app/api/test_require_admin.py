"""Encaixe da auth de admin. Hoje no-op — o teste tranca o contrato para quando
a auth chegar: não-admin recebe 404, nunca 403 (a página não revela que existe)."""

import inspect

import pytest

from src.app.api.dependencies.require_admin import require_admin


def test_is_a_coroutine_dependency():
    assert inspect.iscoroutinefunction(require_admin)


@pytest.mark.asyncio
async def test_today_it_lets_everyone_through():
    assert await require_admin() is None


def test_module_documents_the_404_decision():
    """Se alguém trocar por 403 sem discutir, este teste chama a atenção."""
    assert "404" in (require_admin.__doc__ or "")
