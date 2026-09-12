from src.domain.lessons.services.coverage_policy import classify_coverage


def test_a_near_hit_is_covered():
    assert classify_coverage(0.10) == "covered"


def test_the_near_threshold_is_inclusive():
    assert classify_coverage(0.35) == "covered"


def test_between_the_thresholds_is_partial():
    assert classify_coverage(0.45) == "partial"


def test_the_far_threshold_is_still_partial():
    assert classify_coverage(0.55) == "partial"


def test_beyond_the_far_threshold_is_a_content_gap():
    assert classify_coverage(0.80) == "gap"


def test_no_chunk_at_all_is_a_gap_too():
    """Aula indexada mas sem trecho nenhum é lacuna, não 'sem informação'."""
    assert classify_coverage(None) == "gap"
