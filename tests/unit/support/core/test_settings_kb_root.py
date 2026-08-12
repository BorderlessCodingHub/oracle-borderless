from src.support.core.settings import Settings


def test_kb_root_page_ids_defaults_to_empty_tuple():
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_IDS is None
    assert s.kb_root_page_ids == ()


def test_kb_root_page_ids_splits_and_normalizes(monkeypatch):
    monkeypatch.setenv(
        "NOTION_KB_ROOT_PAGE_IDS",
        "23d8d655-c889-806d-8828-d527ce6a1529, 25C8D655C8898041-8C78C300C4A2B496",
    )
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == (
        "23d8d655c889806d8828d527ce6a1529",
        "25c8d655c88980418c78c300c4a2b496",
    )


def test_kb_root_page_ids_dedupes_preserving_order(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "abc-123, def456, ABC123")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ("abc123", "def456")


def test_kb_root_page_ids_ignores_blanks_and_commented_entries(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "abc123, , # desativado, def456")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ("abc123", "def456")


def test_kb_root_page_ids_empty_string_is_no_roots(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_IDS", "   ")
    s = Settings(_env_file=None)
    assert s.kb_root_page_ids == ()
