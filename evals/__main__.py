"""Entrypoint do harness de eval: `python -m evals` (real) ou
`python -m evals --dry-run` (só carrega/valida casos e imprime contagens)."""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from evals.models import CATEGORIES, load_cases
from evals.report import aggregate, render_table, write_report
from evals.runner import run_all
from src.support.core.session_scope import run_in_async_session

_CASES_PATH = Path(__file__).parent / "cases" / "golden_set.json"
_REPORTS_DIR = Path(__file__).parent / "reports"


def _dry_run() -> int:
    cases = load_cases(_CASES_PATH)
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

    cases = load_cases(_CASES_PATH)

    async def _work():
        # A Action é montada AQUI DENTRO de propósito: DocumentChunkRepository lê a
        # sessão do ContextVar no __init__ (regra 3), e fora de um request só existe
        # sessão dentro deste escopo. Construir antes deixa o repo com session=None.
        return await run_all(
            cases,
            graph=get_turn_graph_runner(enable_tools=False),
            search=SearchKnowledgeBaseAction(embeddings=get_embeddings_client()),
            judge=get_answer_judge(),
        )

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
