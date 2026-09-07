"""Escopos de sessão fora do request (ADR-0020): `async_session_scope` é o
context manager que o corpo SSE usa para o prelúdio do turno;
`run_in_async_session` é açúcar por cima dele."""

import asyncio

import pytest

from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.session_scope import async_session_scope, run_in_async_session


class _FakeSession:
    def __init__(self, seen: dict) -> None:
        self._seen = seen

    async def commit(self):
        self._seen["committed"] = True

    async def rollback(self):
        self._seen["rolledback"] = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _install_fake_session(monkeypatch) -> dict:
    seen: dict = {}
    monkeypatch.setattr("src.support.core.session_scope.AsyncSessionLocal", lambda: _FakeSession(seen))
    return seen


@pytest.mark.asyncio
async def test_run_in_async_session_populates_and_clears_context(monkeypatch):
    seen = _install_fake_session(monkeypatch)

    async def work():
        assert CurrentAsyncSessionContext.get() is not None  # sessão viva durante fn
        return "ok"

    result = await run_in_async_session(work)

    assert result == "ok"
    assert seen.get("committed") is True
    assert CurrentAsyncSessionContext.get() is None  # limpo ao final


@pytest.mark.asyncio
async def test_async_session_scope_sets_the_context_inside_and_commits_and_clears_after(monkeypatch):
    seen = _install_fake_session(monkeypatch)

    async with async_session_scope() as session:
        assert CurrentAsyncSessionContext.get() is session
        assert "committed" not in seen  # o commit é no fim do bloco, não na entrada

    assert seen.get("committed") is True
    assert "rolledback" not in seen
    assert CurrentAsyncSessionContext.get() is None


@pytest.mark.asyncio
async def test_async_session_scope_rolls_back_and_clears_on_a_regular_exception(monkeypatch):
    seen = _install_fake_session(monkeypatch)

    with pytest.raises(RuntimeError, match="boom"):
        async with async_session_scope():
            raise RuntimeError("boom")

    assert seen.get("rolledback") is True
    assert "committed" not in seen
    assert CurrentAsyncSessionContext.get() is None


@pytest.mark.asyncio
async def test_async_session_scope_rolls_back_and_clears_on_cancellation(monkeypatch):
    """Desconexão do cliente no prelúdio: o Starlette cancela a task do corpo e
    `CancelledError` (BaseException) atravessa o `async with`. Tem que fazer
    rollback e limpar o ContextVar — `except Exception` não pegaria."""
    seen = _install_fake_session(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        async with async_session_scope():
            raise asyncio.CancelledError()

    assert seen.get("rolledback") is True
    assert "committed" not in seen
    assert CurrentAsyncSessionContext.get() is None


@pytest.mark.asyncio
async def test_async_session_scope_lets_a_generator_be_iterated_inside_it(monkeypatch):
    """O caso de uso real: iterar um gerador (o prelúdio) dentro do escopo."""
    _install_fake_session(monkeypatch)
    seen_inside: list = []

    async def gen():
        yield 1
        yield 2

    async with async_session_scope():
        async for item in gen():
            seen_inside.append((item, CurrentAsyncSessionContext.get() is not None))

    assert seen_inside == [(1, True), (2, True)]
    assert CurrentAsyncSessionContext.get() is None
