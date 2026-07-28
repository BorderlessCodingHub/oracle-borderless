from src.support.utils.notion_ids import normalize_page_id


def test_removes_dashes_and_lowercases():
    assert normalize_page_id("23D8D655-C889-806D-8828-D527CE6A1529") == (
        "23d8d655c889806d8828d527ce6a1529"
    )


def test_already_normalized_is_unchanged():
    assert normalize_page_id("23d8d655c889806d8828d527ce6a1529") == (
        "23d8d655c889806d8828d527ce6a1529"
    )


def test_strips_surrounding_whitespace():
    assert normalize_page_id("  23d8d655-c889  ") == "23d8d655c889"


def test_none_and_empty_return_none():
    assert normalize_page_id(None) is None
    assert normalize_page_id("") is None
    assert normalize_page_id("   ") is None
