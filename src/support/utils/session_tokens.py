"""Token de sessão do oráculo (ADR-0018) — utilitário genérico (sem regra de domínio).

O token cru (`secrets.token_urlsafe(32)`) só existe no cookie httpOnly; o banco
guarda o SHA-256 — um dump vazado não vira sessão. Usado por login, resolve e
logout; vive em support/utils porque é só secrets+hashlib, sem regra de negócio.
"""

import hashlib
import secrets


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
