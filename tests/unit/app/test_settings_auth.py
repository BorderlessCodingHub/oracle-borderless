"""Settings de auth (ADR-0017): defaults e normalização da allowlist."""

from src.support.core.settings import Settings


def test_auth_settings_defaults():
    s = Settings(_env_file=None)
    assert s.BORDERLESS_AUTH_URL == "https://api.borderlesscoding.com"
    assert s.BORDERLESS_AUTH_KEY_HEADER == "x-api-key"
    assert s.BORDERLESS_JWT_ALGORITHM == "RS256"
    assert s.BORDERLESS_AUTH_API_KEY is None
    assert s.BORDERLESS_JWT_VERIFY_KEY is None
    assert s.ADMIN_EMAILS == ""
    assert s.admin_emails == frozenset()


def test_admin_emails_normaliza_espacos_e_caixa():
    s = Settings(_env_file=None, ADMIN_EMAILS=" Ana@X.com , beto@y.com ,, ")
    assert s.admin_emails == frozenset({"ana@x.com", "beto@y.com"})


def test_cors_origins_vazio_por_padrao():
    s = Settings(_env_file=None)
    assert s.CORS_ORIGINS == ""
    assert s.cors_origins == []


def test_cors_origins_trima_e_descarta_vazios():
    s = Settings(
        _env_file=None,
        CORS_ORIGINS=" https://app.borderlesscoding.com , https://oraculo.dev ,, ",
    )
    assert s.cors_origins == ["https://app.borderlesscoding.com", "https://oraculo.dev"]
