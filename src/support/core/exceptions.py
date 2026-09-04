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


class ForbiddenError(DomainError):
    """Login recusado pela plataforma por estado da conta (desativada, banida,
    convite pendente). A mensagem É da plataforma e VAI ao usuário — única
    exceção deliberada à regra "nunca erro cru" (ADR-0018)."""


class RateLimitedError(DomainError):
    """Muitas tentativas — janela de rate limit estourada."""


class ExternalServiceUnavailableError(DomainError):
    """Serviço externo (plataforma de auth) indisponível ou fora do contrato."""
