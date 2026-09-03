"""Exceções de domínio. Portáveis (HTTP, CLI, jobs) — nunca acoplam a FastAPI.

O `exception_handlers` da camada `app/api` traduz cada uma para HTTP.
"""


class DomainError(Exception):
    """Base para todas as exceções de domínio."""


class NotFoundError(DomainError):
    """Recurso não encontrado."""


class DomainConflictError(DomainError):
    """Conflito de regra de negócio (ex.: documento já ingerido)."""


class ValidationError(DomainError):
    """Falha de validação de regra de domínio."""


class UnauthorizedDomainError(DomainError):
    """Operação não permitida pelo domínio."""


class InvalidCredentialsError(DomainError):
    """Login recusado pela plataforma (credenciais inválidas)."""


class RateLimitedError(DomainError):
    """Muitas tentativas — janela de rate limit estourada."""


class ExternalServiceUnavailableError(DomainError):
    """Serviço externo (plataforma de auth) indisponível ou fora do contrato."""
