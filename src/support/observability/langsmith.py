"""Tracing no LangSmith.

O SDK do LangSmith lê o ambiente, então esta é a ÚNICA exceção à regra de não
exportar chave: `configure_langsmith()` empurra as settings para `os.environ` no
boot, num ponto só, em vez de o .env ser exportado inteiro.

E-mail nunca sai em claro: só um hash estável, que agrupa turnos por pessoa sem
expor identidade. O endereço em claro fica em `agent_traces`, que é nosso.
"""

import hashlib
import logging
import os

from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_HASH_LEN = 16


def configure_langsmith() -> None:
    """Idempotente. Chamada no lifespan."""
    if not settings.LANGSMITH_TRACING:
        os.environ.pop("LANGSMITH_TRACING", None)
        return
    if not settings.LANGSMITH_API_KEY:
        raise ValueError("LANGSMITH_API_KEY não configurada, mas LANGSMITH_TRACING=true")
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    logger.info("tracing do LangSmith ativo no projeto %s", settings.LANGSMITH_PROJECT)


def hash_email(email: str | None) -> str | None:
    if not email:
        return None
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:_HASH_LEN]


def run_url(run_id: str | None) -> str | None:
    base = settings.LANGSMITH_PROJECT_URL
    if not base or not run_id:
        return None
    return f"{base.rstrip('/')}/r/{run_id}"
