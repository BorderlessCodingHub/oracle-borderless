import json

import pytest

from src.support.observability.eval_report_store import EvalReportStore


def test_read_returns_none_when_directory_is_absent(tmp_path):
    store = EvalReportStore(tmp_path / "nao-existe")
    assert store.read() is None
    assert store.history() == []


def test_read_returns_the_report(tmp_path):
    (tmp_path / "eval_report.json").write_text(
        json.dumps({"verdict": "pass", "metrics": {}}), encoding="utf-8"
    )
    assert EvalReportStore(tmp_path).read()["verdict"] == "pass"


def test_history_returns_one_dict_per_line_newest_first(tmp_path):
    lines = [json.dumps({"run": n}) for n in (1, 2, 3)]
    (tmp_path / "eval_runs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert [d["run"] for d in EvalReportStore(tmp_path).history()] == [3, 2, 1]


def test_history_skips_blank_lines(tmp_path):
    (tmp_path / "eval_runs.jsonl").write_text('{"run": 1}\n\n', encoding="utf-8")
    assert len(EvalReportStore(tmp_path).history()) == 1


def test_corrupt_report_raises_a_clear_error(tmp_path):
    (tmp_path / "eval_report.json").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError, match="eval_report.json"):
        EvalReportStore(tmp_path).read()
