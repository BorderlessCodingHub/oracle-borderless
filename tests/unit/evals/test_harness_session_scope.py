"""O harness roda dentro de um escopo de sessão — e monta a Action lá dentro.

`DocumentChunkRepository` lê a sessão do ContextVar no `__init__` (regra 3). Fora
de um request não existe sessão, então o entrypoint precisa abrir uma antes de
construir `SearchKnowledgeBaseAction`. Construir a Action fora do escopo deixa o
repo com `session=None` e o primeiro caso morre com AttributeError.
"""

import evals.__main__ as entry
from evals.models import EvalCase
from src.support.clients.borderless.borderless_navigation_client import NavigationResult
from src.support.core.context import CurrentAsyncSessionContext


class _FakeSession:
    """Só um sentinela — nada aqui toca banco."""


async def _fake_run_in_async_session(fn):
    CurrentAsyncSessionContext.set(_FakeSession())
    try:
        return await fn()
    finally:
        CurrentAsyncSessionContext.clear()


def _patch_common(monkeypatch):
    """Tudo que `_run` toca fora do que cada teste quer observar."""
    # Sem chave o entrypoint sai cedo (o juiz é OpenAI); aqui a chave é dummy e
    # nada chama a OpenAI de verdade — o juiz também é fake.
    monkeypatch.setattr("src.support.core.settings.settings.OPENAI_API_KEY", "sk-eval-dummy")
    monkeypatch.setattr(entry, "run_in_async_session", _fake_run_in_async_session)
    monkeypatch.setattr(entry, "write_report", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.support.clients.embeddings.embeddings_client.get_embeddings_client",
        lambda: object(),
    )
    monkeypatch.setattr("evals.judge.judge.get_answer_judge", lambda: object())


async def test_search_action_is_built_inside_the_session_scope(monkeypatch):
    seen = {}

    async def fake_run_all(cases, *, graph, search, judge, extra_config=None):
        seen["session"] = search.chunk_repo.session
        return []

    _patch_common(monkeypatch)
    monkeypatch.setattr(entry, "run_all", fake_run_all)
    monkeypatch.setattr(entry, "load_cases", lambda _path: [])
    monkeypatch.setattr(
        "src.support.agent.graph.get_turn_graph_runner", lambda **kw: object()
    )

    await entry._run()

    assert isinstance(seen["session"], _FakeSession)


async def test_navigation_cases_run_with_tools_and_a_canned_navigation_client(monkeypatch):
    calls = []
    runners = []

    async def fake_run_all(cases, *, graph, search, judge, extra_config=None):
        calls.append({"cases": [c.id for c in cases], "graph": graph, "extra_config": extra_config})
        return []

    def fake_runner(**kw):
        runners.append(kw)
        return f"runner(enable_tools={kw.get('enable_tools')})"

    nav_case = EvalCase(
        id="nav-1", category="navigation", question="quero praticar algoritmos",
        expected_destination="code_breakers", mode="navigate",
    )
    other_case = EvalCase(id="a-1", category="answerable", question="q")

    _patch_common(monkeypatch)
    monkeypatch.setattr(entry, "run_all", fake_run_all)
    monkeypatch.setattr(
        entry, "load_cases",
        lambda path: [nav_case] if "navigation_set" in str(path) else [other_case],
    )
    monkeypatch.setattr("src.support.agent.graph.get_turn_graph_runner", fake_runner)

    await entry._run()

    # Duas passadas: as categorias antigas SEM tools (como sempre), a navegação
    # COM tools — sem o tool loop o modelo nunca chamaria `navigate_platform`.
    assert [c["cases"] for c in calls] == [["a-1"], ["nav-1"]]
    assert calls[0]["extra_config"] is None
    assert [r.get("enable_tools") for r in runners] == [False, True]

    extra = calls[1]["extra_config"]
    assert extra["platform_token"] == "eval"
    client = extra["navigation_client"]
    result = await client.resolve("eval", "code_breakers")
    assert isinstance(result, NavigationResult)
    assert result.destination["id"] == "code_breakers"


async def test_dry_run_counts_both_case_files(capsys):
    assert entry._dry_run() == 0
    out = capsys.readouterr().out
    assert "navigation=" in out
    assert "answerable=" in out
    # a contagem total soma os dois arquivos
    total = int(out.split("Loaded ")[1].split(" ")[0])
    counts = dict(
        part.strip().split("=") for part in out.split(": ", 1)[1].split(",")
    )
    assert total == sum(int(v) for v in counts.values())
    assert int(counts["navigation"]) >= 8
