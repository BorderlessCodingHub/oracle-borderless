"""Hash de e-mail e deep link. O e-mail em claro NUNCA sai para o SaaS."""

import pytest

from src.support.core.settings import settings
from src.support.observability.langsmith import configure_langsmith, hash_email, run_url


def test_hashing_is_stable_for_the_same_person():
    assert hash_email("duanne@x.com") == hash_email("duanne@x.com")


def test_hashing_separates_different_people():
    assert hash_email("a@x.com") != hash_email("b@x.com")


def test_the_hash_never_contains_the_address():
    hashed = hash_email("duanne@x.com")
    assert "duanne" not in hashed and "@" not in hashed


def test_an_anonymous_turn_has_no_hash():
    assert hash_email(None) is None
    assert hash_email("") is None


def test_no_link_without_a_configured_project_url(monkeypatch):
    monkeypatch.setattr(settings, "LANGSMITH_PROJECT_URL", None)
    assert run_url("abc") is None


def test_no_link_without_a_run_id(monkeypatch):
    monkeypatch.setattr(settings, "LANGSMITH_PROJECT_URL", "https://smith.langchain.com/o/x/projects/p/y")
    assert run_url(None) is None


def test_the_link_points_at_the_run(monkeypatch):
    monkeypatch.setattr(settings, "LANGSMITH_PROJECT_URL", "https://smith.langchain.com/o/x/projects/p/y/")
    assert run_url("abc") == "https://smith.langchain.com/o/x/projects/p/y/r/abc"


def test_tracing_off_does_not_export(monkeypatch):
    """Default desligado: sem chave, nada sai da máquina."""
    monkeypatch.setattr(settings, "LANGSMITH_TRACING", False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    configure_langsmith()
    import os

    assert os.environ.get("LANGSMITH_TRACING") != "true"


def test_tracing_on_requires_a_key(monkeypatch):
    monkeypatch.setattr(settings, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(settings, "LANGSMITH_API_KEY", None)
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        configure_langsmith()
