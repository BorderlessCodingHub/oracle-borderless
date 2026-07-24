from src.support.core.settings import Settings


def test_kb_root_page_id_defaults_to_none():
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_ID is None


def test_kb_root_page_id_reads_from_env(monkeypatch):
    monkeypatch.setenv("NOTION_KB_ROOT_PAGE_ID", "abc123")
    s = Settings(_env_file=None)
    assert s.NOTION_KB_ROOT_PAGE_ID == "abc123"
