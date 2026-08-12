import pytest

from src.support.core.lifespan import LifespanManager
from src.support.core.settings import settings


def test_raises_when_only_the_old_root_env_var_is_set(monkeypatch):
    # Deploy com NOTION_KB_ROOT_PAGE_ID (nome antigo, ADR-0011) e sem
    # NOTION_KB_ROOT_PAGE_IDS: sem esta checagem, a aplicação subiria muda,
    # com escopo de KB vazio, e o oráculo responderia "não sei" para tudo.
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", "abc123", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", None, raising=False)

    with pytest.raises(RuntimeError, match="ADR-0014"):
        LifespanManager._validate_kb_root_env()


def test_does_not_raise_when_the_new_var_is_also_set(monkeypatch):
    # A env var nova vence: presença da antiga junto da nova não é erro (ex.:
    # janela de migração, ou alguém deixou a antiga no .env por descuido).
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", "abc123", raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta


def test_does_not_raise_in_the_normal_case(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_ID", None, raising=False)
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)

    LifespanManager._validate_kb_root_env()  # não levanta
