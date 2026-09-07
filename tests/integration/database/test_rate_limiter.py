"""Rate limit durável: janela fixa, contagem por chave, fail-open."""

import pytest

from src.support.core.rate_limit import rate_limiter
from src.support.core.rate_limit.rate_limiter import rate_limit


@pytest.mark.asyncio
async def test_permite_ate_o_limite_e_bloqueia_depois(db_session):
    key = "signin:teste@x.com"
    for _ in range(3):
        assert await rate_limit(key, limit=3, window_ms=600_000) is True
    assert await rate_limit(key, limit=3, window_ms=600_000) is False


@pytest.mark.asyncio
async def test_chaves_diferentes_nao_se_misturam(db_session):
    assert await rate_limit("signin:a@x.com", limit=1, window_ms=600_000) is True
    assert await rate_limit("signin:b@x.com", limit=1, window_ms=600_000) is True


@pytest.mark.asyncio
async def test_janela_nova_zera_o_contador(db_session, monkeypatch):
    key = "signin:janela@x.com"
    assert await rate_limit(key, limit=1, window_ms=600_000) is True
    assert await rate_limit(key, limit=1, window_ms=600_000) is False
    # Avança o relógio para o bucket seguinte.
    real_bucket = rate_limiter._current_bucket
    monkeypatch.setattr(
        rate_limiter, "_current_bucket", lambda window_ms: real_bucket(window_ms) + 1
    )
    assert await rate_limit(key, limit=1, window_ms=600_000) is True


@pytest.mark.asyncio
async def test_fail_open_quando_o_banco_falha(db_session, monkeypatch):
    async def _explode(*args, **kwargs):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(db_session, "execute", _explode)
    assert await rate_limit("signin:x@x.com", limit=1, window_ms=600_000) is True


@pytest.mark.asyncio
async def test_fail_open_com_erro_real_de_banco_nao_envenena_a_transacao(db_session):
    chave_longa_demais = "x" * 300  # estoura VARCHAR(255) -> DataError do Postgres
    assert await rate_limit(chave_longa_demais, limit=1, window_ms=600_000) is True

    # O savepoint (`begin_nested`) isolou o erro: a sessão continua utilizável
    # para uma chamada seguinte, bem-formada, na mesma transação.
    assert await rate_limit("signin:pos-erro@x.com", limit=1, window_ms=600_000) is True
