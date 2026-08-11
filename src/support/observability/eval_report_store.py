"""Leitura dos reports do harness de eval. I/O de filesystem — infraestrutura,
não domínio. É também onde um exportador OTel entraria depois."""

import json
from pathlib import Path

from src.support.core.settings import settings


class EvalReportStore:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory or settings.EVAL_REPORTS_DIR)

    def read(self) -> dict | None:
        path = self.directory / "eval_report.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"eval_report.json ilegível em {path}: {exc}") from exc

    def history(self, limit: int = 20) -> list[dict]:
        path = self.directory / "eval_runs.jsonl"
        if not path.is_file():
            return []
        runs: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # uma linha ruim não invalida o histórico
        return list(reversed(runs))[:limit]
