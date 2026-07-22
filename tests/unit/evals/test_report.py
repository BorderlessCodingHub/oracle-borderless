import json

import pytest

from evals.models import (
    APPROPRIATE_REFUSAL,
    CITATION_SUPPORT,
    FAITHFULNESS,
    CaseResult,
    MetricScore,
)
from evals.report import aggregate, render_table, write_report


def _r(case_id, category, **scores):
    return CaseResult(case_id, category, "answer", {k: MetricScore(v, "r") for k, v in scores.items()})


def test_mean_only_over_applicable_cases_and_verdict_pass():
    results = [
        _r("a1", "answerable", faithfulness=0.9, citation_support=0.85),
        _r("a2", "answerable", faithfulness=0.9, citation_support=0.85),
        _r("r1", "refusal", appropriate_refusal=0.95),
    ]
    report = aggregate(results)

    faith = next(m for m in report.metrics if m.metric == FAITHFULNESS)
    refusal = next(m for m in report.metrics if m.metric == APPROPRIATE_REFUSAL)
    assert faith.n == 2 and faith.mean == pytest.approx(0.9)
    assert refusal.n == 1
    assert report.passed is True


def test_verdict_fails_when_a_metric_mean_below_threshold():
    results = [
        _r("a1", "answerable", faithfulness=0.5, citation_support=0.9),
        _r("a2", "answerable", faithfulness=0.5, citation_support=0.9),
    ]
    report = aggregate(results)
    assert report.passed is False
    faith = next(m for m in report.metrics if m.metric == FAITHFULNESS)
    assert faith.passed is False


def test_below_floor_cases_are_listed_even_if_mean_passes():
    results = [
        _r("good1", "answerable", faithfulness=1.0, citation_support=1.0),
        _r("good2", "answerable", faithfulness=1.0, citation_support=1.0),
        _r("weak", "answerable", faithfulness=0.3, citation_support=1.0),
    ]
    report = aggregate(results)
    assert ("weak", FAITHFULNESS, 0.3) in report.below_floor


def test_empty_results_do_not_pass():
    report = aggregate([])
    assert report.passed is False


def test_write_report_emits_json_and_appends_jsonl(tmp_path):
    from datetime import datetime, timezone

    results = [_r("a1", "answerable", faithfulness=0.9, citation_support=0.9)]
    report = aggregate(results)
    write_report(report, tmp_path, datetime(2026, 7, 22, tzinfo=timezone.utc))
    write_report(report, tmp_path, datetime(2026, 7, 22, tzinfo=timezone.utc))

    latest = json.loads((tmp_path / "eval_report.json").read_text())
    assert latest["passed"] is True
    assert "metrics" in latest
    lines = (tmp_path / "eval_runs.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2  # appended, not overwritten


def test_render_table_is_a_nonempty_string():
    report = aggregate([_r("a1", "answerable", faithfulness=0.9, citation_support=0.9)])
    table = render_table(report)
    assert isinstance(table, str) and FAITHFULNESS in table
