"""A regra 1 do CLAUDE.md, como teste: src/domain/ não importa o framework do
agente. O grafo mora em support/ e recebe as Actions de domínio injetadas como
ports — se alguém inverter isso, este teste é o que avisa.

O teste anterior (test_oracle_engine_boundary.py) NÃO fazia isto: só exercitava
um fake. A fronteira nunca esteve protegida.
"""

import pathlib

_FORBIDDEN = ("langgraph", "langchain", "pydantic_ai")
_DOMAIN = pathlib.Path(__file__).parents[4] / "src" / "domain"


def _offending_lines(path: pathlib.Path) -> list[str]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if any(pkg in stripped for pkg in _FORBIDDEN):
            hits.append(f"{path}:{lineno}: {stripped}")
    return hits


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


_PROTOCOL = ("ag_ui",)
_SUPPORT_AGENT = _DOMAIN.parent / "support" / "agent"


def _protocol_imports(path: pathlib.Path) -> list[str]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if any(pkg in stripped for pkg in _PROTOCOL):
            hits.append(f"{path}:{lineno}: {stripped}")
    return hits


def test_domain_and_graph_do_not_import_the_ui_protocol():
    """ADR-0019: o AG-UI é assunto da camada app. O port fala em dataclasses
    puras; quem traduz para eventos é src/app/api/streaming/."""
    roots = [_DOMAIN, _SUPPORT_AGENT]
    offenders = [hit for root in roots for py in root.rglob("*.py") for hit in _protocol_imports(py)]
    assert offenders == [], "ag_ui vazou para o domínio ou para o grafo:\n" + "\n".join(offenders)
