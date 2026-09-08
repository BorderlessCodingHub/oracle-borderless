"""A regra 1 do CLAUDE.md, como teste: src/domain/ não importa o framework do
agente. O grafo mora em support/ e recebe as Actions de domínio injetadas como
ports — se alguém inverter isso, este teste é o que avisa.

O teste anterior (test_oracle_engine_boundary.py) NÃO fazia isto: só exercitava
um fake. A fronteira nunca esteve protegida.
"""

import pathlib

_FORBIDDEN = ("langgraph", "langchain", "pydantic_ai")
_DOMAIN = pathlib.Path(__file__).parents[4] / "src" / "domain"


def _import_lines(path: pathlib.Path, needles: tuple[str, ...]) -> list[str]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if any(pkg in stripped for pkg in needles):
            hits.append(f"{path}:{lineno}: {stripped}")
    return hits


def _offending_lines(path: pathlib.Path) -> list[str]:
    return _import_lines(path, _FORBIDDEN)


def test_domain_does_not_import_the_agent_framework():
    assert _DOMAIN.is_dir(), f"caminho do domínio não encontrado: {_DOMAIN}"
    offenders = [hit for py in _DOMAIN.rglob("*.py") for hit in _offending_lines(py)]
    assert offenders == [], (
        "src/domain/ importou o framework do agente — a inversão de dependência "
        "quebrou. O grafo deve receber as Actions como ports.\n" + "\n".join(offenders)
    )


def test_the_forbidden_list_actually_matches_something():
    """Guarda contra o teste virar tautologia se os pacotes mudarem de nome."""
    support = _DOMAIN.parent / "support" / "agent"
    found = [hit for py in support.rglob("*.py") for hit in _offending_lines(py)]
    assert found, "nenhum import do framework em support/agent/ — a lista _FORBIDDEN está obsoleta?"


_APP_LAYER = ("src.app",)
_SUPPORT_AGENT = _DOMAIN.parent / "support" / "agent"


def test_domain_and_graph_do_not_import_the_app_layer():
    """ADR-0021: o fio (`event:`/`data:`, request schema) é assunto da camada
    app. O port fala `GraphEvent`; quem serializa é src/app/api/streaming/. Se
    o grafo ou o domínio importarem `src.app`, a dependência inverteu."""
    roots = [_DOMAIN, _SUPPORT_AGENT]
    offenders = [hit for root in roots for py in root.rglob("*.py") for hit in _import_lines(py, _APP_LAYER)]
    assert offenders == [], "src.app vazou para o domínio ou para o grafo:\n" + "\n".join(offenders)


def test_the_app_layer_list_actually_matches_something():
    controllers = _DOMAIN.parent / "app" / "api" / "controllers"
    found = [hit for py in controllers.rglob("*.py") for hit in _import_lines(py, _APP_LAYER)]
    assert found, "nenhum import de src.app em app/api/controllers/ — a lista está obsoleta?"


_SESSION_OPENERS = ("AsyncSessionLocal", "session_scope")


def test_domain_does_not_open_database_sessions():
    """Regra 3 + ADR-0020: o domínio LÊ a sessão do ContextVar; quem abre escopo
    (request, corpo SSE, job, eval) é app/console/evals. Se uma Action importar
    `AsyncSessionLocal` ou `session_scope`, o ciclo de vida da sessão vazou."""
    offenders = [hit for py in _DOMAIN.rglob("*.py") for hit in _import_lines(py, _SESSION_OPENERS)]
    assert offenders == [], "src/domain/ está abrindo sessão de banco:\n" + "\n".join(offenders)


def test_the_session_openers_list_actually_matches_something():
    app_and_support = [_DOMAIN.parent / "app", _DOMAIN.parent / "support" / "core"]
    found = [hit for root in app_and_support for py in root.rglob("*.py") for hit in _import_lines(py, _SESSION_OPENERS)]
    assert found, "nenhum import de AsyncSessionLocal/session_scope em app/ ou support/core/ — a lista está obsoleta?"
