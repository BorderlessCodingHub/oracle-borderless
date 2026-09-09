"""Entrypoint do harness de eval: `python -m evals` (real) ou
`python -m evals --dry-run` (só carrega/valida casos e imprime contagens)."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from evals.models import CATEGORIES, load_cases
from evals.report import aggregate, render_table, write_report
from evals.runner import run_all
from src.support.clients.borderless.borderless_navigation_client import NavigationResult
from src.support.core.session_scope import run_in_async_session

_CASES_DIR = Path(__file__).parent / "cases"
_CASES_PATH = _CASES_DIR / "golden_set.json"
_NAVIGATION_CASES_PATH = _CASES_DIR / "navigation_set.json"
_NAVIGATION_FIXTURES_PATH = _CASES_DIR / "navigation_fixtures.json"
_REPORTS_DIR = Path(__file__).parent / "reports"


def _all_cases() -> list:
    """Os dois arquivos, com os ids conferidos entre eles — `load_cases` só
    enxerga duplicata dentro do próprio arquivo."""
    cases = [*load_cases(_CASES_PATH), *load_cases(_NAVIGATION_CASES_PATH)]
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id across case files: {case.id}")
        seen.add(case.id)
    return cases


def _navigation_config() -> dict:
    """`configurable` extra dos casos de navegação: token de fachada e cliente
    enlatado. O eval mede a ESCOLHA do destino pelo modelo — a resolução real é
    da borderless-api e tem os testes dela; chamá-la aqui tornaria a métrica
    dependente de rede e de dados de um usuário real.

    O import do fake é local de propósito: `evals` não pode depender de `tests`
    em tempo de import — só quando há caso de navegação para rodar."""
    from tests.fakes.fake_navigation_client import FakeNavigationClient

    raw = json.loads(_NAVIGATION_FIXTURES_PATH.read_text(encoding="utf-8"))
    results = {
        destination: NavigationResult(
            destination=dict(payload["destination"]),
            access=str(payload["access"]),
            unlock=dict(payload["unlock"]) if payload.get("unlock") else None,
            signals=dict(payload.get("signals") or {}),
            alternatives=list(payload.get("alternatives") or []),
        )
        for destination, payload in raw.items()
        if not destination.startswith("_")  # chaves de comentário
    }
    catalog = [
        {"id": destination, "path": result.destination.get("path", ""), "kind": "static"}
        for destination, result in results.items()
    ]
    return {
        "platform_token": "eval",
        # R12/ADR-0022: a tool e o bloco de prompt de navegação só existem para
        # sessões que sabem navegar — o eval de navegação simula uma delas.
        "navigation_enabled": True,
        "navigation_client": FakeNavigationClient(results=results, catalog=catalog),
    }


def _dry_run() -> int:
    cases = _all_cases()
    counts = {c: 0 for c in CATEGORIES}
    for case in cases:
        counts[case.category] += 1
    summary = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"Loaded {len(cases)} cases: {summary}")
    return 0


async def _run() -> int:
    from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
    from src.support.agent.graph import get_turn_graph_runner
    from src.support.clients.embeddings.embeddings_client import get_embeddings_client
    from src.support.core.settings import settings
    from evals.judge.judge import get_answer_judge

    key = settings.OPENAI_API_KEY
    if not key:
        print(
            "SKIPPED — nenhuma avaliação executada (sem OPENAI_API_KEY; o juiz do "
            "eval é OpenAI, independente de LLM_PROVIDER)"
        )
        return 2

    cases = _all_cases()
    navigation_cases = [c for c in cases if c.category == "navigation"]
    other_cases = [c for c in cases if c.category != "navigation"]

    async def _work():
        # A Action é montada AQUI DENTRO de propósito: DocumentChunkRepository lê a
        # sessão do ContextVar no __init__ (regra 3), e fora de um request só existe
        # sessão dentro deste escopo. Construir antes deixa o repo com session=None.
        search = SearchKnowledgeBaseAction(embeddings=get_embeddings_client())
        judge = get_answer_judge()
        # Duas passadas com runners diferentes de propósito. `enable_tools` é
        # tudo-ou-nada: ligá-lo dá ao modelo web_search e fetch_notion_page
        # junto com navigate_platform, e as categorias de conhecimento medem
        # justamente a resposta SEM essas saídas. A navegação, ao contrário,
        # não existe sem o tool loop.
        results = await run_all(
            other_cases,
            graph=get_turn_graph_runner(enable_tools=False),
            search=search,
            judge=judge,
        )
        if navigation_cases:
            results += await run_all(
                navigation_cases,
                graph=get_turn_graph_runner(enable_tools=True),
                search=search,
                judge=judge,
                extra_config=_navigation_config(),
            )
        return results

    results = await run_in_async_session(_work)
    report = aggregate(results)
    print(render_table(report))
    write_report(report, _REPORTS_DIR, datetime.now(timezone.utc))
    return 0 if report.passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="carrega e valida os casos e imprime contagens por categoria; não chama modelos nem DB",
    )
    args = parser.parse_args()
    if args.dry_run:
        return _dry_run()
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
