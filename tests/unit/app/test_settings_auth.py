"""Settings de auth (ADR-0017/0018): defaults, allowlist e ausência das envs mortas."""

from src.support.core.settings import Settings


def test_auth_settings_defaults():
    s = Settings(_env_file=None)
    assert s.BORDERLESS_AUTH_URL == "https://api.borderlesscoding.com"
    assert s.ADMIN_EMAILS == ""
    assert s.admin_emails == frozenset()


def test_is_development_so_no_ambiente_de_dev():
    assert Settings(_env_file=None).is_development is True
    assert Settings(_env_file=None, ENVIRONMENT="staging").is_development is False
    assert Settings(_env_file=None, ENVIRONMENT="production").is_development is False


def test_envs_da_v1_nao_existem_mais():
    """ADR-0018: login é público e o token é opaco — nada de key nem JWT."""
    s = Settings(_env_file=None)
    for name in (
        "BORDERLESS_AUTH_API_KEY",
        "BORDERLESS_AUTH_KEY_HEADER",
        "BORDERLESS_JWT_ALGORITHM",
        "BORDERLESS_JWT_VERIFY_KEY",
    ):
        assert not hasattr(s, name), name


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
