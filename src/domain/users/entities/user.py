from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """Usuário da plataforma Borderless (ADR-0017). Puro — sem SQLAlchemy.

    Nada persiste aqui: o oráculo não tem tabela de usuários (spec §4.2).
    """

    id: str
    email: str
    name: str | None = None
    username: str | None = None
    career_stage: str | None = None
    email_verified: bool | None = None
