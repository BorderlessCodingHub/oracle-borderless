"""Escopos de sessão async FORA do ciclo de request.

Quem abre escopo é a camada `app` (corpo SSE), `console` (jobs, commands, seeds)
ou `evals` — nunca o domínio. Os repositórios continuam lendo a sessão via
`CurrentAsyncSessionContext.get()` (regra 3); estes helpers só a colocam lá.

Usos:
- `async_session_scope()` — context manager: para trabalho que precisa ITERAR um
  gerador dentro do escopo (o prelúdio do turno, ADR-0020).
- `run_in_async_session(fn)` — açúcar por cima do anterior, para uma coroutine
  (persistir a resposta e o trace depois do stream).

Mesma mecânica de Job.execute()/Commands/Seeds: abre AsyncSessionLocal, popula o
contexto, comita no fim (ou rollback na exceção), limpa.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal

T = TypeVar("T")


@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Abre uma sessão, popula o ContextVar, comita no fim (ou rollback na
    exceção) e limpa o ContextVar — sempre, inclusive em cancelamento.

    `except BaseException` (não `Exception`): `CancelledError` é BaseException e
    precisa fazer rollback antes de subir — é o que acontece quando o cliente
    desconecta durante o prelúdio do turno.
    """
    async with AsyncSessionLocal() as session:
        CurrentAsyncSessionContext.set(session)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            CurrentAsyncSessionContext.clear()


async def run_in_async_session(fn: Callable[[], Awaitable[T]]) -> T:
    async with async_session_scope():
        return await fn()
