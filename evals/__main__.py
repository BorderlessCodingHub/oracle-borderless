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
    from src.support.agent.oracle_engine import get_oracle_engine
    from src.support.agent.retrieval_gate import get_retrieval_gate
    from src.support.clients.embeddings.embeddings_client import get_embeddings_client
    from src.support.core.settings import settings
    from evals.judge.judge import get_answer_judge

    key = settings.OPENAI_API_KEY if settings.LLM_PROVIDER == "openai" else settings.ANTHROPIC_API_KEY
    if not key:
        print(f"Sem API key para o provedor '{settings.LLM_PROVIDER}'; pulando o judge eval.")
        return 0

    cases = load_cases(_CASES_PATH)
    results = await run_all(
        cases,
        gate=get_retrieval_gate(),
        search=SearchKnowledgeBaseAction(embeddings=get_embeddings_client()),
        engine=get_oracle_engine(),
        judge=get_answer_judge(),
    )
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
