import pytest

from src.support.core.lifespan import LifespanManager
from src.support.core.settings import settings


def test_raises_when_the_plural_root_env_var_is_still_set(monkeypatch):
    # Deploy defasado: o escopo agora vem da permissão da integração
    # (ADR-0015). Uma env var de root sobrando significa que alguém acha que
    # ainda controla o escopo por configuração — falhar alto é melhor que
    # deixar a crença passar silenciosa.
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    with pytest.raises(RuntimeError, match="ADR-0015"):
        LifespanManager._validate_kb_root_env()


def test_raises_when_the_old_singular_env_var_is_still_set(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", "abc123", raising=False)

    with pytest.raises(RuntimeError, match="ADR-0015"):
        LifespanManager._validate_kb_root_env()


def test_does_not_raise_when_neither_is_set(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta


def test_blank_value_is_not_treated_as_set(monkeypatch):
    # `NOTION_KB_ROOT_PAGE_IDS=` no .env chega como string vazia, não None.
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "   ", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta
