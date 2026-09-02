"""O harness roda dentro de um escopo de sessão — e monta a Action lá dentro.

`DocumentChunkRepository` lê a sessão do ContextVar no `__init__` (regra 3). Fora
de um request não existe sessão, então o entrypoint precisa abrir uma antes de
construir `SearchKnowledgeBaseAction`. Construir a Action fora do escopo deixa o
repo com `session=None` e o primeiro caso morre com AttributeError.
"""

import evals.__main__ as entry
from src.support.core.context import CurrentAsyncSessionContext


class _FakeSession:
    """Só um sentinela — nada aqui toca banco."""


async def _fake_run_in_async_session(fn):
    CurrentAsyncSessionContext.set(_FakeSession())
    try:
        return await fn()
    finally:
        CurrentAsyncSessionContext.clear()


async def test_search_action_is_built_inside_the_session_scope(monkeypatch):
    seen = {}

    async def fake_run_all(cases, *, graph, search, judge):
        seen["session"] = search.chunk_repo.session
        return []

    monkeypatch.setattr(entry, "run_in_async_session", _fake_run_in_async_session)
    monkeypatch.setattr(entry, "run_all", fake_run_all)
    monkeypatch.setattr(entry, "load_cases", lambda _path: [])
    monkeypatch.setattr(entry, "write_report", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.support.agent.graph.get_turn_graph_runner", lambda **kw: object()
    )
    monkeypatch.setattr(
        "src.support.clients.embeddings.embeddings_client.get_embeddings_client",
        lambda: object(),
    )
    monkeypatch.setattr("evals.judge.judge.get_answer_judge", lambda: object())

    await entry._run()

    assert isinstance(seen["session"], _FakeSession)
