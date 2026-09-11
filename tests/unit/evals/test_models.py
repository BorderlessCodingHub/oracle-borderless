import json

import pytest

from evals.models import (
    APPROPRIATE_REFUSAL,
    CITATION_SUPPORT,
    FAITHFULNESS,
    NAVIGATION_TARGET,
    load_cases,
    metrics_for_category,
)


def test_metrics_for_category_mapping():
    assert metrics_for_category("answerable") == (FAITHFULNESS, CITATION_SUPPORT)
    assert metrics_for_category("multi_turn") == (FAITHFULNESS, CITATION_SUPPORT)
    assert metrics_for_category("refusal") == (APPROPRIATE_REFUSAL,)
    assert metrics_for_category("adversarial") == (FAITHFULNESS,)


def test_load_cases_reads_the_seed_golden_set():
    cases = load_cases("evals/cases/golden_set.json")
    assert len(cases) >= 12
    cats = {c.category for c in cases}
    assert {"answerable", "refusal", "multi_turn", "adversarial"} <= cats


def test_load_cases_rejects_unknown_category(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"id": "x", "category": "nope", "question": "q"}]))
    with pytest.raises(ValueError, match="unknown category"):
        load_cases(p)


def test_load_cases_requires_poisoned_context_for_adversarial(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"id": "x", "category": "adversarial", "question": "q"}]))
    with pytest.raises(ValueError, match="poisoned_context"):
        load_cases(p)


def test_load_cases_requires_should_refuse_for_refusal(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"id": "x", "category": "refusal", "question": "q"}]))
    with pytest.raises(ValueError, match="should_refuse"):
        load_cases(p)


def test_load_cases_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([
        {"id": "dup", "category": "answerable", "question": "a"},
        {"id": "dup", "category": "answerable", "question": "b"},
    ]))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(p)


def test_navigation_metric_mapping():
    assert metrics_for_category("navigation") == (NAVIGATION_TARGET,)


def test_load_cases_reads_the_navigation_set():
    cases = load_cases("evals/cases/navigation_set.json")
    assert len(cases) >= 8
    assert {c.category for c in cases} == {"navigation"}
    # o caso ambíguo pede AUSÊNCIA de navegação — destino esperado nulo
    assert any(c.expected_destination is None for c in cases)
    assert {c.expected_destination for c in cases} >= {
        "code_breakers", "trail", "events", "program", "settings",
        "settings_purchases", "leaderboard",
    }
    assert any(c.mode == "navigate" for c in cases)


def test_load_cases_requires_expected_destination_key_for_navigation(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([{"id": "x", "category": "navigation", "question": "q"}]))
    with pytest.raises(ValueError, match="expected_destination"):
        load_cases(p)


def test_load_cases_accepts_null_expected_destination(tmp_path):
    p = tmp_path / "ok.json"
    p.write_text(json.dumps([
        {"id": "x", "category": "navigation", "question": "q", "expected_destination": None, "mode": "navigate"}
    ]))
    case = load_cases(p)[0]
    assert case.expected_destination is None
    assert case.mode == "navigate"
