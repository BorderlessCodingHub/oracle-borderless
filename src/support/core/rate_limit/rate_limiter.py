"""Rate limit de janela fixa em Postgres (ADR-0017).

Um único upsert atômico por tentativa; savepoint próprio para que um erro de
banco não envenene a transação do request. FAIL-OPEN de propósito, mas
restrito a erros de banco: uma indisponibilidade transitória do Postgres não
pode derrubar o login inteiro. Erros de programação/wiring (window_ms
inválido, sessão ausente do contexto) propagam normalmente — não são
mascarados como "permitido".
"""

import logging
import time

from sqlalchemy import text

from src.support.core.context import CurrentAsyncSessionContext

logger = logging.getLogger(__name__)

_UPSERT = text(
    """
    INSERT INTO rate_limits (key, window_start, count)
    VALUES (:key, :bucket, 1)
    ON CONFLICT (key) DO UPDATE SET
      count = CASE
        WHEN rate_limits.window_start = :bucket THEN rate_limits.count + 1
        ELSE 1
      END,
      window_start = :bucket
    RETURNING count
    """
)


def _current_bucket(window_ms: int) -> int:
    return int(time.time() * 1000) // window_ms


async def rate_limit(key: str, limit: int, window_ms: int) -> bool:
    """True = permitido. Conta a tentativa atual (inclusive a que estoura)."""
    bucket = _current_bucket(window_ms)
    session = CurrentAsyncSessionContext.get()
    try:
        async with session.begin_nested():
            result = await session.execute(_UPSERT, {"key": key, "bucket": bucket})
            return int(result.scalar_one()) <= limit
    except Exception:
        logger.exception("rate limit indisponível — fail-open")
        return True
