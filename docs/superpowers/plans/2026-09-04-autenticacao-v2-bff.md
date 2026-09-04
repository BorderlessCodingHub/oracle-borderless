# Autenticação v2 (BFF) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refatorar a auth v1 (JWT validado localmente, token no localStorage do SPA) para o BFF do ADR-0018: o `accessToken` opaco da plataforma vive só na tabela `sessions`, o SPA recebe cookie httpOnly `ob_session`, e cada request valida a sessão contra `GET /api/users/profile` com cache de 60s e fail-open de até 10min.

**Architecture:** `POST /auth/login` (público) chama o signin da plataforma **sem key**, persiste uma `UserSession` (hash SHA-256 do token nosso + accessToken da plataforma + snapshot do usuário) e devolve `Set-Cookie`. `require_user` lê o cookie → `ResolveSessionAction` (hash → repositório → validação com cache/fail-open) → `AuthenticatedUser` no contexto. `GET /auth/me` e `POST /auth/logout` ficam no `router` protegido. O SPA perde `session.ts`/`authHeaders` e restaura identidade via `/auth/me` (200/401/erro de rede = os três estados do `RequireAuth`).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, httpx (`MockTransport` nos testes), pytest-asyncio; React 18 + Vitest + Testing Library no frontend. `pyjwt` é **removido**.

**Spec:** `docs/autenticacao.md` (v2 — §0 tem o delta exato) + `docs/adr/0018-auth-bff-token-opaco.md`. Contrato da plataforma: `autenticacao_plataform.md` (raiz, untracked).

## Global Constraints

- Regras do `CLAUDE.md`: Entity = dataclass pura (sem sqlalchemy/fastapi/pydantic); Model = SQLAlchemy; conversão só no Mapper; repositórios pegam sessão de `CurrentAsyncSessionContext.get()`; caso de uso = Action com `execute()`; controllers finos; schemas Pydantic só em `src/app/api/`.
- **Nenhum token da plataforma** em resposta de API, log ou browser. Nunca logar senha nem token de sessão cru.
- Cookie: nome `ob_session`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=604800` (7d), `Secure` quando `settings.ENVIRONMENT != "development"`.
- Constantes (não envs): `PLATFORM_CHECK_TTL_S = 60`, `FAIL_OPEN_MAX_S = 600`.
- Rate limit do login **mantido igual**: chave `signin:<email>`, 10 tentativas / 600_000 ms.
- Erros da plataforma mapeados por `error.type`: `VALIDATION`/`UNAUTHORIZED` → `invalid-credentials` (401); `FORBIDDEN` → `forbidden` (403) **com a `message` da plataforma**; `TOO_MANY_REQUESTS` → `rate-limited` (429); `INTERNAL`/rede/timeout/fora do contrato → `unavailable` (503).
- 401 do oráculo continua único e genérico (`{"detail": "not-authenticated"}`); `/ops` sem admin continua 404.
- Envs que **morrem**: `BORDERLESS_AUTH_API_KEY`, `BORDERLESS_AUTH_KEY_HEADER`, `BORDERLESS_JWT_ALGORITHM`, `BORDERLESS_JWT_VERIFY_KEY`. Ficam `BORDERLESS_AUTH_URL`, `ADMIN_EMAILS`, `CORS_ORIGINS`. Nenhuma env nova.
- Sem dependência nova (`pyproject.toml`). `pyjwt[crypto]` sai.
- Nomenclatura (decisão deste plano, desvio cosmético do spec que fala em `Session`): entity **`UserSession`**, `UserSessionModel` (tabela `sessions`), `UserSessionMapper`, `UserSessionRepository` — evita colisão mental com `AsyncSession` do SQLAlchemy, que os repositórios já chamam de `self.session`.
- Testes de integração de API batem no banco de `settings.DB_NAME` (dev, porta 5434 no `.env`); a fixture `db_session` usa `DB_NAME_TEST`. **Ambos** precisam de `alembic upgrade head` após a migration nova.
- Português nos comentários/docstrings, como o resto do repo.

---

## Mapa de arquivos

**Backend — criar**
- `src/domain/users/entities/user_session.py` — entity `UserSession`
- `src/domain/users/models/__init__.py`, `src/domain/users/models/user_session.py` — `UserSessionModel`
- `src/domain/users/mappers/__init__.py`, `src/domain/users/mappers/user_session_mapper.py`
- `src/domain/users/repositories/__init__.py`, `src/domain/users/repositories/user_session_repository.py`
- `src/domain/users/services/__init__.py`, `src/domain/users/services/session_tokens.py` — gerar/hashear token
- `src/domain/users/actions/resolve_session_action.py`, `src/domain/users/actions/sign_out_action.py`
- `src/app/api/session_cookie.py` — nome do cookie + set/clear
- `database/migrations/versions/0009_sessions.py`

**Backend — modificar**
- `src/support/core/exceptions.py` (+`ForbiddenError`), `src/app/api/exception_handlers.py` (403 com message)
- `src/support/clients/borderless/borderless_auth_client.py` (sem key; `get_profile`; `sign_out`; erros por `type`)
- `src/domain/users/actions/sign_in_action.py`, `src/domain/users/actions/__init__.py`, `src/domain/users/dtos/sign_in_result.py`, `src/domain/users/entities/authenticated_user.py`
- `src/app/api/dependencies/require_user.py`, `src/app/api/controllers/auth_controller.py`, `src/app/api/routes/auth.py`, `src/app/api/responses/auth_responses.py`
- `src/support/core/settings.py`, `.env.example`, `main.py` (comentário do CORS), `pyproject.toml`, `uv.lock`
- `tests/fakes/auth.py`, `tests/conftest.py` e todos os testes que importam `auth_headers`
- `CLAUDE.md` (linha da stack de auth + lista de ADRs), `docs/autenticacao.md` (status)

**Frontend — apagar**
- `frontend/src/lib/auth/session.ts`, `frontend/src/lib/auth/session.test.ts`

**Frontend — criar**
- `frontend/src/test/authFetch.ts` — stub de `fetch` que responde `/auth/me` e `/auth/logout`

**Frontend — modificar**
- `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/conversations.ts`, `frontend/src/hooks/useAuth.tsx`, `frontend/src/components/AuthSettings/AuthSettings.tsx`, `frontend/src/features/auth/LoginPage.tsx`, `frontend/vite.config.ts`
- Testes: `useAuth.test.tsx`, `RequireAuth.test.tsx`, `App.test.tsx`, `Sidebar.test.tsx`, `LoginPage.test.tsx`

---

### Task 0 (opcional, não bloqueia): validar o contrato da plataforma com curl

Passo 1 do §11 do spec. **Depende de um usuário de teste em staging (pendência §8) — se não houver credenciais, registrar isso no relatório final e seguir.** Nada do código depende disto porque todos os testes mockam a plataforma.

- [ ] **Step 1: signin sem key**

```bash
curl -s https://api.borderlesscoding.com/api/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email":"<usuario-teste>","password":"<senha>"}' | head -c 600
```
Esperado: `200` com `data.user` e `data.token.accessToken`, `expiresIn: 604800`.

- [ ] **Step 2: profile + signout com o token**

```bash
TOKEN=<accessToken>
curl -s -o /dev/null -w "%{http_code}\n" https://api.borderlesscoding.com/api/users/profile -H "Authorization: Bearer $TOKEN"   # 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://api.borderlesscoding.com/api/auth/signout -H "Authorization: Bearer $TOKEN"
curl -s -o /dev/null -w "%{http_code}\n" https://api.borderlesscoding.com/api/users/profile -H "Authorization: Bearer $TOKEN"   # 401 depois do signout
```

---

### Task 1: Persistência de sessão — `UserSession` (entity, model, mapper, repository, tokens, migration)

**Files:**
- Create: `src/domain/users/entities/user_session.py`
- Create: `src/domain/users/models/__init__.py`, `src/domain/users/models/user_session.py`
- Create: `src/domain/users/mappers/__init__.py`, `src/domain/users/mappers/user_session_mapper.py`
- Create: `src/domain/users/repositories/__init__.py`, `src/domain/users/repositories/user_session_repository.py`
- Create: `src/domain/users/services/__init__.py`, `src/domain/users/services/session_tokens.py`
- Create: `database/migrations/versions/0009_sessions.py`
- Test: `tests/unit/domain/users/test_session_tokens.py`, `tests/integration/domain/users/test_user_session_repository.py`

**Interfaces:**
- Produces:
  - `UserSession(uuid, token_hash, platform_access_token, user_id, user_email, user_name, user_username, last_platform_check_at, created_at, updated_at)` (dataclass).
  - `UserSessionRepository().get_by_token_hash(token_hash: str) -> UserSession | None`, `.create(s: UserSession) -> UserSession`, `.mark_platform_checked(session_id: UUID, checked_at: datetime) -> None`, `.delete(session_id: UUID) -> None`.
  - `generate_session_token() -> str` (urlsafe, 32 bytes), `hash_session_token(raw: str) -> str` (hex SHA-256, 64 chars).

- [ ] **Step 1: teste unitário dos tokens**

`tests/unit/domain/users/test_session_tokens.py`:
```python
"""Token de sessão do oráculo (ADR-0018): aleatório no cookie, só o hash no banco."""

from src.domain.users.services.session_tokens import generate_session_token, hash_session_token


def test_token_gerado_e_aleatorio_e_longo():
    a, b = generate_session_token(), generate_session_token()
    assert a != b
    assert len(a) >= 40  # 32 bytes urlsafe ≈ 43 chars


def test_hash_e_sha256_hex_deterministico():
    assert hash_session_token("abc") == hash_session_token("abc")
    assert hash_session_token("abc") != hash_session_token("abd")
    assert len(hash_session_token("abc")) == 64
    assert hash_session_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
```

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/unit/domain/users/test_session_tokens.py -v`
Expected: FAIL (`ModuleNotFoundError: src.domain.users.services`)

- [ ] **Step 3: implementar tokens**

`src/domain/users/services/__init__.py`:
```python
from src.domain.users.services.session_tokens import generate_session_token, hash_session_token

__all__ = ["generate_session_token", "hash_session_token"]
```

`src/domain/users/services/session_tokens.py`:
```python
"""Token de sessão do oráculo (ADR-0018).

O token cru (`secrets.token_urlsafe(32)`) só existe no cookie httpOnly; o banco
guarda o SHA-256 — um dump vazado não vira sessão. Domain Service porque a
regra não tem dono natural entre as Actions (login, resolve e logout usam).
"""

import hashlib
import secrets


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/unit/domain/users/test_session_tokens.py -v`
Expected: PASS

- [ ] **Step 5: entity, model, mapper**

`src/domain/users/entities/user_session.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class UserSession:
    """Sessão do oráculo (ADR-0018). Pura — sem SQLAlchemy.

    `token_hash` é o SHA-256 do token que vive no cookie `ob_session`;
    `platform_access_token` é o token opaco da Borderless — nunca sai do servidor.
    `user_*` é snapshot do login para `/auth/me` responder sem ir à rede.
    `last_platform_check_at` é o cache da validação contra a plataforma.
    """

    uuid: UUID
    token_hash: str
    platform_access_token: str
    user_id: str
    user_email: str
    user_name: str | None
    user_username: str | None
    last_platform_check_at: datetime
    created_at: datetime
    updated_at: datetime

    def seconds_since_platform_check(self, now: datetime) -> float:
        return (now - self.last_platform_check_at).total_seconds()
```

`src/domain/users/models/__init__.py`: arquivo vazio (o `database/env.py` importa os submódulos por autodiscovery).

`src/domain/users/models/user_session.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.support.core.mixins import ApplyRelations, HasTimestamps, HasUUID
from src.support.core.models.base_model import BaseModel


class UserSessionModel(BaseModel, HasUUID, HasTimestamps, ApplyRelations):
    """Persistência da sessão do oráculo (ADR-0018). Só mapeamento."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    platform_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_platform_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

`src/domain/users/mappers/__init__.py`:
```python
from src.domain.users.mappers.user_session_mapper import UserSessionMapper

__all__ = ["UserSessionMapper"]
```

`src/domain/users/mappers/user_session_mapper.py`:
```python
from src.domain.users.entities.user_session import UserSession
from src.domain.users.models.user_session import UserSessionModel


class UserSessionMapper:
    @staticmethod
    def to_entity(model: UserSessionModel) -> UserSession:
        return UserSession(
            uuid=model.uuid,
            token_hash=model.token_hash,
            platform_access_token=model.platform_access_token,
            user_id=model.user_id,
            user_email=model.user_email,
            user_name=model.user_name,
            user_username=model.user_username,
            last_platform_check_at=model.last_platform_check_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def to_model_attrs(entity: UserSession) -> dict:
        return {
            "uuid": entity.uuid,
            "token_hash": entity.token_hash,
            "platform_access_token": entity.platform_access_token,
            "user_id": entity.user_id,
            "user_email": entity.user_email,
            "user_name": entity.user_name,
            "user_username": entity.user_username,
            "last_platform_check_at": entity.last_platform_check_at,
        }
```

- [ ] **Step 6: repository**

`src/domain/users/repositories/__init__.py`:
```python
from src.domain.users.repositories.user_session_repository import UserSessionRepository

__all__ = ["UserSessionRepository"]
```

`src/domain/users/repositories/user_session_repository.py`:
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update

from src.domain.users.entities.user_session import UserSession
from src.domain.users.mappers import UserSessionMapper
from src.domain.users.models.user_session import UserSessionModel
from src.support.core.context import CurrentAsyncSessionContext


class UserSessionRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        result = await self.session.execute(
            select(UserSessionModel).where(UserSessionModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return UserSessionMapper.to_entity(model) if model else None

    async def create(self, user_session: UserSession) -> UserSession:
        model = UserSessionModel(**UserSessionMapper.to_model_attrs(user_session))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return UserSessionMapper.to_entity(model)

    async def mark_platform_checked(self, session_id: UUID, checked_at: datetime) -> None:
        await self.session.execute(
            update(UserSessionModel)
            .where(UserSessionModel.uuid == session_id)
            .values(last_platform_check_at=checked_at)
        )

    async def delete(self, session_id: UUID) -> None:
        await self.session.execute(
            delete(UserSessionModel).where(UserSessionModel.uuid == session_id)
        )
```

- [ ] **Step 7: migration**

`database/migrations/versions/0009_sessions.py`:
```python
"""sessions — sessão do oráculo: hash do cookie + accessToken da plataforma (ADR-0018).

Revision ID: 0009_sessions
Revises: 0008_rate_limits
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_sessions"
down_revision = "0008_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("uuid", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("platform_access_token", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("user_email", sa.String(320), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=True),
        sa.Column("user_username", sa.String(255), nullable=True),
        sa.Column("last_platform_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_email", "sessions", ["user_email"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_email", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
```

- [ ] **Step 8: aplicar nos dois bancos e checar**

```bash
uv run alembic upgrade head
DB_NAME=oracle_borderless_test uv run alembic upgrade head
uv run alembic check
```
Expected: os dois `upgrade` terminam em `0009_sessions`; `alembic check` imprime "No new upgrade operations detected." Se reclamar do nome do índice, alinhe o Model/migration (o `unique=True, index=True` do SQLAlchemy gera `ix_sessions_token_hash`).

- [ ] **Step 9: teste de integração do repository**

`tests/integration/domain/users/__init__.py` vazio (crie se a pasta `tests/integration/domain/users/` não existir; `tests/integration/domain/` já existe).

`tests/integration/domain/users/test_user_session_repository.py`:
```python
"""UserSessionRepository: hash único, snapshot, cache de validação e delete."""

from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository


def _session(token_hash: str, email: str = "ana@x.com") -> UserSession:
    now = datetime.now(timezone.utc)
    return UserSession(
        uuid=uuid7(),
        token_hash=token_hash,
        platform_access_token="plat-abc",
        user_id="u-1",
        user_email=email,
        user_name="Ana",
        user_username="ana",
        last_platform_check_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_e_get_by_token_hash(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("h" * 64))
    found = await repo.get_by_token_hash("h" * 64)
    assert found is not None
    assert found.uuid == created.uuid
    assert found.platform_access_token == "plat-abc"
    assert found.user_email == "ana@x.com"
    assert found.user_name == "Ana"
    assert await repo.get_by_token_hash("x" * 64) is None


@pytest.mark.asyncio
async def test_mark_platform_checked_atualiza_o_cache(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("c" * 64))
    later = created.last_platform_check_at + timedelta(minutes=5)
    await repo.mark_platform_checked(created.uuid, later)
    found = await repo.get_by_token_hash("c" * 64)
    assert found.last_platform_check_at == later


@pytest.mark.asyncio
async def test_delete_remove_a_sessao(db_session):
    repo = UserSessionRepository()
    created = await repo.create(_session("d" * 64))
    await repo.delete(created.uuid)
    assert await repo.get_by_token_hash("d" * 64) is None
```

- [ ] **Step 10: rodar**

Run: `uv run pytest tests/integration/domain/users tests/unit/domain/users/test_session_tokens.py -v`
Expected: PASS (4 + 2)

- [ ] **Step 11: commit**

```bash
git add src/domain/users database/migrations/versions/0009_sessions.py tests/unit/domain/users/test_session_tokens.py tests/integration/domain/users
git commit -m "feat(auth): tabela sessions + UserSession (entity/model/mapper/repository) e tokens de sessão (ADR-0018)"
```

---

### Task 2: `BorderlessAuthClient` v2 — sem key, erros por `error.type`, `get_profile`, `sign_out`, `ForbiddenError`

**Files:**
- Modify: `src/support/core/exceptions.py`
- Modify: `src/app/api/exception_handlers.py`
- Modify: `src/support/clients/borderless/borderless_auth_client.py` (reescrever)
- Modify: `src/support/clients/borderless/__init__.py`
- Test: `tests/unit/support/test_borderless_auth_client.py` (reescrever)

**Interfaces:**
- Produces:
  - `ForbiddenError(DomainError)` — `str(exc)` é a mensagem da plataforma; handler HTTP → `403 {"detail": "forbidden", "message": str(exc)}`.
  - `PlatformProfile(id, email, name, username, membership, community_role)`.
  - `BorderlessAuthClient(transport=None).sign_in(email, password) -> PlatformSignIn` (sem header de key).
  - `.get_profile(access_token: str) -> PlatformProfile | None` — `None` = 401 (sessão inválida na plataforma); lança `ExternalServiceUnavailableError` em rede/timeout/5xx/429/corpo fora do contrato.
  - `.sign_out(access_token: str) -> None` — best-effort, nunca lança.

- [ ] **Step 1: exceção + handler**

Em `src/support/core/exceptions.py`, adicionar após `InvalidCredentialsError`:
```python
class ForbiddenError(DomainError):
    """Login recusado pela plataforma por estado da conta (desativada, banida,
    convite pendente). A mensagem É da plataforma e VAI ao usuário — única
    exceção deliberada à regra "nunca erro cru" (ADR-0018)."""
```

Em `src/app/api/exception_handlers.py`, importar `ForbiddenError` e adicionar antes do handler de `RateLimitedError`:
```python
    @app.exception_handler(ForbiddenError)
    async def _forbidden(request: Request, exc: ForbiddenError):
        return JSONResponse(
            status_code=403, content={"detail": "forbidden", "message": str(exc)}
        )
```

- [ ] **Step 2: reescrever os testes do client**

Substituir `tests/unit/support/test_borderless_auth_client.py` inteiro por:
```python
"""Bridge com a plataforma (ADR-0018): signin público, erros por `error.type`,
profile como validação de sessão e signout best-effort."""

import httpx
import pytest

from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
    RateLimitedError,
)

OK_BODY = {
    "message": "ok",
    "data": {
        "user": {
            "id": "u-1",
            "email": "Hello@Example.com",
            "name": "Hello",
            "emailVerified": True,
            "username": "hello",
            "careerStage": "junior_transition",
        },
        "token": {"accessToken": "opaque-abc", "expiresIn": 604800},
    },
}

PROFILE_BODY = {
    "data": {
        "user": {
            "id": "u-1",
            "name": "Hello",
            "email": "hello@example.com",
            "username": "hello",
            "communityRole": "MEMBER",
            "membership": "BASE",
        }
    }
}


def _error(status: int, type_: str, message: str = "msg") -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "error": {
                "code": f"AUTH-{type_}-{status}",
                "type": type_,
                "domain": "AUTH",
                "message": message,
                "timestamp": "2026-09-04T12:00:00.000Z",
                "details": {},
            }
        },
    )


def _client(handler) -> BorderlessAuthClient:
    return BorderlessAuthClient(transport=httpx.MockTransport(handler))


# --- sign_in ---


@pytest.mark.asyncio
async def test_signin_e_publico_sem_key_e_parseia_user_e_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = {k.lower() for k in request.headers.keys()}
        return httpx.Response(200, json=OK_BODY)

    result = await _client(handler).sign_in("hello@example.com", "s3nh4")
    assert seen["url"].endswith("/api/auth/signin")
    assert "x-api-key" not in seen["headers"]
    assert "authorization" not in seen["headers"]
    assert result.user.email == "hello@example.com"  # normalizado
    assert result.user.career_stage == "junior_transition"
    assert result.access_token == "opaque-abc"
    assert result.expires_in == 604800


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,type_", [(400, "VALIDATION"), (401, "UNAUTHORIZED"), (400, "UNAUTHORIZED")]
)
async def test_validation_e_unauthorized_viram_invalid_credentials(status, type_):
    with pytest.raises(InvalidCredentialsError):
        await _client(lambda _: _error(status, type_)).sign_in("a@x.com", "errada")


@pytest.mark.asyncio
async def test_forbidden_carrega_a_message_da_plataforma():
    handler = lambda _: _error(403, "FORBIDDEN", "Sua conta está desativada.")
    with pytest.raises(ForbiddenError) as exc:
        await _client(handler).sign_in("a@x.com", "s")
    assert str(exc.value) == "Sua conta está desativada."


@pytest.mark.asyncio
async def test_too_many_requests_vira_rate_limited():
    with pytest.raises(RateLimitedError):
        await _client(lambda _: _error(429, "TOO_MANY_REQUESTS")).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_internal_5xx_e_rede_viram_unavailable():
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(500, "INTERNAL")).sign_in("a@x.com", "s")

    def handler_net(_):
        raise httpx.ConnectError("down")

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_net).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_status_sem_envelope_cai_no_mapeamento_por_status():
    """Envelope ausente (proxy, HTML) — o status ainda diz o essencial."""
    with pytest.raises(InvalidCredentialsError):
        await _client(lambda _: httpx.Response(401, text="nope")).sign_in("a@x.com", "s")
    with pytest.raises(RateLimitedError):
        await _client(lambda _: httpx.Response(429, text="slow")).sign_in("a@x.com", "s")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(502, text="bad")).sign_in("a@x.com", "s")


@pytest.mark.asyncio
async def test_200_com_corpo_fora_do_contrato_vira_unavailable():
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(200, json={"data": {}})).sign_in("a@x.com", "s")


# --- get_profile ---


@pytest.mark.asyncio
async def test_get_profile_200_manda_bearer_sem_cookie_e_parseia():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["cookie"] = request.headers.get("cookie")
        return httpx.Response(200, json=PROFILE_BODY)

    profile = await _client(handler).get_profile("opaque-abc")
    assert seen["url"].endswith("/api/users/profile")
    assert seen["auth"] == "Bearer opaque-abc"
    assert seen["cookie"] is None
    assert profile.id == "u-1"
    assert profile.email == "hello@example.com"
    assert profile.membership == "BASE"
    assert profile.community_role == "MEMBER"


@pytest.mark.asyncio
async def test_get_profile_401_devolve_none():
    assert await _client(lambda _: _error(401, "UNAUTHORIZED")).get_profile("x") is None


@pytest.mark.asyncio
async def test_get_profile_rede_5xx_429_e_fora_do_contrato_lancam_unavailable():
    def handler_net(_):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler_net).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(500, "INTERNAL")).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: _error(429, "TOO_MANY_REQUESTS")).get_profile("x")
    with pytest.raises(ExternalServiceUnavailableError):
        await _client(lambda _: httpx.Response(200, json={"data": {}})).get_profile("x")


# --- sign_out ---


@pytest.mark.asyncio
async def test_sign_out_manda_bearer_e_engole_erros():
    seen = {}

    def handler_ok(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"message": "ok"})

    await _client(handler_ok).sign_out("opaque-abc")
    assert seen["url"].endswith("/api/auth/signout")
    assert seen["auth"] == "Bearer opaque-abc"

    def handler_net(_):
        raise httpx.ConnectError("down")

    await _client(handler_net).sign_out("opaque-abc")  # não lança
    await _client(lambda _: _error(500, "INTERNAL")).sign_out("opaque-abc")  # não lança
```

- [ ] **Step 3: rodar e ver falhar**

Run: `uv run pytest tests/unit/support/test_borderless_auth_client.py -v`
Expected: FAIL (ImportError de `ForbiddenError` até o Step 1; depois, `get_profile`/`sign_out` inexistentes e header de key ainda enviado)

- [ ] **Step 4: reescrever o client**

Substituir `src/support/clients/borderless/borderless_auth_client.py` inteiro por:
```python
"""Bridge com a plataforma Borderless (ADR-0018; spec §3).

O login é PÚBLICO (não existe key de app). O `accessToken` é sessão opaca do
Better Auth: validar = `GET /api/users/profile`. NUNCA logar senha nem token —
os logs registram apenas status/`error.type`.
"""

import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
    RateLimitedError,
)
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class PlatformUser:
    id: str
    email: str
    name: str | None
    username: str | None
    career_stage: str | None
    email_verified: bool | None


@dataclass(frozen=True)
class PlatformSignIn:
    user: PlatformUser
    access_token: str
    expires_in: int | None


@dataclass(frozen=True)
class PlatformProfile:
    """Resposta de `GET /api/users/profile` — o que interessa para autorização."""

    id: str
    email: str
    name: str | None
    username: str | None
    membership: str | None
    community_role: str | None


def _error_envelope(response: httpx.Response) -> tuple[str | None, str | None]:
    """(`error.type`, `error.message`) do envelope da plataforma; (None, None)
    quando o corpo não segue o contrato (proxy devolvendo HTML, etc.)."""
    try:
        error = response.json()["error"]
        type_ = error.get("type")
        message = error.get("message")
        return (str(type_) if type_ else None, str(message) if message else None)
    except (ValueError, KeyError, TypeError, AttributeError):
        return (None, None)


class BorderlessAuthClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # `transport` existe para os testes injetarem httpx.MockTransport.
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}{path}"

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=_TIMEOUT_SECONDS)

    # --- signin ---

    async def sign_in(self, email: str, password: str) -> PlatformSignIn:
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/auth/signin"), json={"email": email, "password": password}
                )
        except httpx.HTTPError as exc:
            logger.error("signin da plataforma falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 200:
            return self._parse_sign_in(response, email)
        self._raise_sign_in_error(response)
        raise ExternalServiceUnavailableError("plataforma indisponível")  # pragma: no cover

    @staticmethod
    def _raise_sign_in_error(response: httpx.Response) -> None:
        """Mapeia por `error.type` (campo estável); cai no status quando o
        envelope não vem. `FORBIDDEN` é o único caso que repassa a message."""
        error_type, message = _error_envelope(response)
        status = response.status_code

        if error_type == "FORBIDDEN" or (error_type is None and status == 403):
            raise ForbiddenError(message or "acesso negado pela plataforma")
        if error_type in ("VALIDATION", "UNAUTHORIZED") or (
            error_type is None and status in (400, 401)
        ):
            raise InvalidCredentialsError("credenciais inválidas")
        if error_type == "TOO_MANY_REQUESTS" or (error_type is None and status == 429):
            raise RateLimitedError("rate limit da plataforma")

        logger.error("signin da plataforma devolveu %s (type=%s)", status, error_type)
        raise ExternalServiceUnavailableError("plataforma indisponível")

    @staticmethod
    def _parse_sign_in(response: httpx.Response, email: str) -> PlatformSignIn:
        try:
            body = response.json()
            user = body["data"]["user"]
            token = body["data"]["token"]
            return PlatformSignIn(
                user=PlatformUser(
                    id=str(user.get("id", "")),
                    email=str(user.get("email") or email).strip().lower(),
                    name=user.get("name"),
                    username=user.get("username"),
                    career_stage=user.get("careerStage"),
                    email_verified=user.get("emailVerified"),
                ),
                access_token=str(token["accessToken"]),
                expires_in=token.get("expiresIn"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("signin 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    # --- profile (validação de sessão) ---

    async def get_profile(self, access_token: str) -> PlatformProfile | None:
        """200 → perfil (sessão válida). 401 → None (expirada/revogada). Qualquer
        outra coisa → ExternalServiceUnavailableError, para o fail-open decidir."""
        try:
            async with self._http() as client:
                response = await client.get(
                    self._url("/api/users/profile"),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("profile da plataforma falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 401:
            return None
        if response.status_code != 200:
            logger.warning("profile da plataforma devolveu %s", response.status_code)
            raise ExternalServiceUnavailableError("plataforma indisponível")

        try:
            user = response.json()["data"]["user"]
            return PlatformProfile(
                id=str(user["id"]),
                email=str(user.get("email") or "").strip().lower(),
                name=user.get("name"),
                username=user.get("username"),
                membership=user.get("membership"),
                community_role=user.get("communityRole"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("profile 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    # --- signout ---

    async def sign_out(self, access_token: str) -> None:
        """Best-effort: invalida a sessão na plataforma. Nunca lança — o logout
        local acontece de qualquer jeito; o log registra a falha."""
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/auth/signout"),
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("signout da plataforma falhou na rede: %s", type(exc).__name__)
            return
        if response.status_code >= 400:
            logger.warning("signout da plataforma devolveu %s", response.status_code)
```

`src/support/clients/borderless/__init__.py`:
```python
from src.support.clients.borderless.borderless_auth_client import (
    BorderlessAuthClient,
    PlatformProfile,
    PlatformSignIn,
    PlatformUser,
)

__all__ = ["BorderlessAuthClient", "PlatformProfile", "PlatformSignIn", "PlatformUser"]
```

- [ ] **Step 5: rodar**

Run: `uv run pytest tests/unit/support/test_borderless_auth_client.py -v`
Expected: PASS (todos). A v1 do `SignInAction` continua funcionando com este client (assinatura de `sign_in` igual).

- [ ] **Step 6: commit**

```bash
git add src/support/core/exceptions.py src/app/api/exception_handlers.py src/support/clients/borderless tests/unit/support/test_borderless_auth_client.py
git commit -m "feat(auth): BorderlessAuthClient v2 — signin público, erros por error.type, get_profile e sign_out (ADR-0018)"
```

---

### Task 3: Actions — `SignInAction` v2, `ResolveSessionAction`, `SignOutAction`

**Files:**
- Modify: `src/domain/users/entities/authenticated_user.py`
- Modify: `src/domain/users/dtos/sign_in_result.py`
- Modify: `src/domain/users/actions/sign_in_action.py`, `src/domain/users/actions/__init__.py`
- Create: `src/domain/users/actions/resolve_session_action.py`, `src/domain/users/actions/sign_out_action.py`
- Test: `tests/unit/domain/users/test_sign_in_action.py` (reescrever), `tests/unit/domain/users/test_resolve_session_action.py`, `tests/unit/domain/users/test_sign_out_action.py`

**Interfaces:**
- Consumes: `UserSession`, `UserSessionRepository`, `generate_session_token`, `hash_session_token` (Task 1); `BorderlessAuthClient.sign_in/get_profile/sign_out` (Task 2).
- Produces:
  - `AuthenticatedUser(id, email, is_admin=False, name=None, username=None)`.
  - `SignInResult(user: User, session_token: str, is_admin: bool)` — `session_token` é o token CRU (só atravessa até o Set-Cookie).
  - `SignInAction(auth_client, sessions=None).execute(email, password) -> SignInResult`.
  - `ResolveSessionAction(auth_client, sessions=None, clock=None).execute(raw_token: str) -> AuthenticatedUser | None`; lança `ExternalServiceUnavailableError` quando a plataforma está fora E a última validação boa tem ≥ 600s. Constantes públicas `PLATFORM_CHECK_TTL_S = 60`, `FAIL_OPEN_MAX_S = 600`.
  - `SignOutAction(auth_client, sessions=None).execute(raw_token: str) -> None`.

- [ ] **Step 1: `AuthenticatedUser` + `SignInResult`**

`src/domain/users/entities/authenticated_user.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidade resolvida da sessão (ADR-0018), injetada no request context
    pelo require_user. `name`/`username` vêm do snapshot da sessão — é o que
    `/auth/me` devolve sem ir à rede."""

    id: str
    email: str
    is_admin: bool = False
    name: str | None = None
    username: str | None = None
```

`src/domain/users/dtos/sign_in_result.py`:
```python
from dataclasses import dataclass

from src.domain.users.entities.user import User


@dataclass(frozen=True)
class SignInResult:
    user: User
    # Token de sessão do oráculo, CRU: só atravessa até o Set-Cookie. Nunca
    # logar nem persistir (o banco guarda o hash).
    session_token: str
    is_admin: bool
```

- [ ] **Step 2: testes do `SignInAction` v2**

Substituir `tests/unit/domain/users/test_sign_in_action.py` inteiro por:
```python
"""SignInAction v2 (ADR-0018): normalização, rate limit, cria sessão com hash,
token cru só no resultado, isAdmin da allowlist."""

import pytest

from src.domain.users.services.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import (
    PlatformSignIn,
    PlatformUser,
)
from src.support.core.exceptions import InvalidCredentialsError, RateLimitedError
from src.support.core.settings import settings


class FakeAuthClient:
    def __init__(self):
        self.calls = []

    async def sign_in(self, email, password):
        self.calls.append((email, password))
        return PlatformSignIn(
            user=PlatformUser(
                id="u-1", email=email, name="Ana", username="ana",
                career_stage="junior_transition", email_verified=True,
            ),
            access_token="opaque-abc",
            expires_in=604800,
        )


class FakeSessions:
    def __init__(self):
        self.created = []

    async def create(self, user_session):
        self.created.append(user_session)
        return user_session


@pytest.fixture(autouse=True)
def _rate_limit_liberado(monkeypatch):
    from src.domain.users.actions import sign_in_action

    async def _ok(key, limit, window_ms):
        return True

    monkeypatch.setattr(sign_in_action, "rate_limit", _ok)


@pytest.mark.asyncio
async def test_normaliza_email_cria_sessao_e_devolve_token_cru():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake, sessions = FakeAuthClient(), FakeSessions()
    result = await SignInAction(auth_client=fake, sessions=sessions).execute("  Ana@X.com ", "s3nh4")

    assert fake.calls == [("ana@x.com", "s3nh4")]
    assert result.user.email == "ana@x.com"
    assert result.user.name == "Ana"
    assert len(result.session_token) >= 40

    assert len(sessions.created) == 1
    row = sessions.created[0]
    assert row.token_hash == hash_session_token(result.session_token)
    assert row.token_hash != result.session_token  # o cru não persiste
    assert row.platform_access_token == "opaque-abc"
    assert (row.user_id, row.user_email, row.user_name, row.user_username) == ("u-1", "ana@x.com", "Ana", "ana")
    assert row.last_platform_check_at is not None  # login = validação fresca


@pytest.mark.asyncio
async def test_vazios_sao_invalid_credentials_sem_ir_a_rede():
    from src.domain.users.actions.sign_in_action import SignInAction

    fake, sessions = FakeAuthClient(), FakeSessions()
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("  ", "x")
    with pytest.raises(InvalidCredentialsError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("a@x.com", "")
    assert fake.calls == []
    assert sessions.created == []


@pytest.mark.asyncio
async def test_rate_limit_estourado_barra_antes_da_rede(monkeypatch):
    from src.domain.users.actions import sign_in_action
    from src.domain.users.actions.sign_in_action import SignInAction

    async def _nao(key, limit, window_ms):
        assert key == "signin:ana@x.com"
        assert (limit, window_ms) == (10, 600_000)
        return False

    monkeypatch.setattr(sign_in_action, "rate_limit", _nao)
    fake, sessions = FakeAuthClient(), FakeSessions()
    with pytest.raises(RateLimitedError):
        await SignInAction(auth_client=fake, sessions=sessions).execute("ana@x.com", "s")
    assert fake.calls == []
    assert sessions.created == []


@pytest.mark.asyncio
async def test_is_admin_vem_da_allowlist(monkeypatch):
    from src.domain.users.actions.sign_in_action import SignInAction

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")
    result = await SignInAction(auth_client=FakeAuthClient(), sessions=FakeSessions()).execute("ana@x.com", "s")
    assert result.is_admin is True

    result = await SignInAction(auth_client=FakeAuthClient(), sessions=FakeSessions()).execute("beto@x.com", "s")
    assert result.is_admin is False
```

- [ ] **Step 3: rodar e ver falhar**

Run: `uv run pytest tests/unit/domain/users/test_sign_in_action.py -v`
Expected: FAIL (`TypeError: unexpected keyword argument 'sessions'`)

- [ ] **Step 4: `SignInAction` v2**

Substituir `src/domain/users/actions/sign_in_action.py` inteiro por:
```python
"""Login via bridge com a plataforma (ADR-0018). NUNCA logar senha/token."""

from datetime import datetime, timezone

from uuid6 import uuid7

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.user import User
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.domain.users.services.session_tokens import generate_session_token, hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import InvalidCredentialsError, RateLimitedError
from src.support.core.rate_limit import rate_limit
from src.support.core.settings import settings

# 10 tentativas por e-mail a cada 10 minutos. Mantido na v2: o limite da
# plataforma (100 req/min) é por IP, e no BFF todas as chamadas saem do nosso.
_SIGNIN_LIMIT = 10
_SIGNIN_WINDOW_MS = 600_000


class SignInAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()

    async def execute(self, email: str, password: str) -> SignInResult:
        email = email.strip().lower()
        if not email or not password:
            raise InvalidCredentialsError("credenciais vazias")

        if not await rate_limit(f"signin:{email}", _SIGNIN_LIMIT, _SIGNIN_WINDOW_MS):
            raise RateLimitedError("muitas tentativas de login")

        data = await self.auth_client.sign_in(email, password)
        user = User(
            id=data.user.id,
            email=data.user.email,
            name=data.user.name,
            username=data.user.username,
            career_stage=data.user.career_stage,
            email_verified=data.user.email_verified,
        )

        raw_token = generate_session_token()
        now = datetime.now(timezone.utc)
        await self.sessions.create(
            UserSession(
                uuid=uuid7(),
                token_hash=hash_session_token(raw_token),
                platform_access_token=data.access_token,
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
                user_username=user.username,
                last_platform_check_at=now,  # o signin acabou de validar
                created_at=now,
                updated_at=now,
            )
        )
        return SignInResult(
            user=user,
            session_token=raw_token,
            is_admin=user.email in settings.admin_emails,
        )
```

- [ ] **Step 5: rodar**

Run: `uv run pytest tests/unit/domain/users/test_sign_in_action.py -v`
Expected: PASS

- [ ] **Step 6: testes do `ResolveSessionAction`**

`tests/unit/domain/users/test_resolve_session_action.py`:
```python
"""ResolveSessionAction (ADR-0018, spec §2): cookie → sessão → validação com
cache de 60s; 401 da plataforma apaga a sessão; fail-open limitado a 10min."""

from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.actions.resolve_session_action import (
    FAIL_OPEN_MAX_S,
    PLATFORM_CHECK_TTL_S,
    ResolveSessionAction,
)
from src.domain.users.entities.user_session import UserSession
from src.domain.users.services.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import PlatformProfile
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.core.settings import settings

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
RAW = "token-cru-de-teste"


def _session(checked_seconds_ago: int) -> UserSession:
    checked = NOW - timedelta(seconds=checked_seconds_ago)
    return UserSession(
        uuid=uuid7(), token_hash=hash_session_token(RAW), platform_access_token="opaque-abc",
        user_id="u-1", user_email="ana@x.com", user_name="Ana", user_username="ana",
        last_platform_check_at=checked, created_at=checked, updated_at=checked,
    )


class FakeSessions:
    def __init__(self, row: UserSession | None):
        self.row = row
        self.marked: list[tuple] = []
        self.deleted: list = []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def mark_platform_checked(self, session_id, checked_at):
        self.marked.append((session_id, checked_at))

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    """`outcome`: PlatformProfile | None (401) | Exception (rede)."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def get_profile(self, access_token):
        self.calls.append(access_token)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


PROFILE = PlatformProfile(id="u-1", email="ana@x.com", name="Ana", username="ana", membership="BASE", community_role="MEMBER")


def _action(sessions, client):
    return ResolveSessionAction(auth_client=client, sessions=sessions, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_sessao_inexistente_devolve_none_sem_ir_a_plataforma():
    client = FakeClient(PROFILE)
    assert await _action(FakeSessions(None), client).execute("qualquer") is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_dentro_do_cache_nao_chama_a_plataforma(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "ana@x.com")
    sessions, client = FakeSessions(_session(PLATFORM_CHECK_TTL_S - 1)), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(RAW)
    assert client.calls == []
    assert sessions.marked == []
    assert (user.id, user.email, user.is_admin, user.name, user.username) == ("u-1", "ana@x.com", True, "Ana", "ana")


@pytest.mark.asyncio
async def test_fora_do_cache_valida_e_atualiza_o_carimbo():
    row = _session(PLATFORM_CHECK_TTL_S)
    sessions, client = FakeSessions(row), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(RAW)
    assert client.calls == ["opaque-abc"]
    assert sessions.marked == [(row.uuid, NOW)]
    assert user.email == "ana@x.com"
    assert user.is_admin is False


@pytest.mark.asyncio
async def test_401_da_plataforma_apaga_a_sessao_e_devolve_none():
    row = _session(PLATFORM_CHECK_TTL_S + 5)
    sessions = FakeSessions(row)
    assert await _action(sessions, FakeClient(None)).execute(RAW) is None
    assert sessions.deleted == [row.uuid]
    assert sessions.marked == []


@pytest.mark.asyncio
async def test_plataforma_fora_dentro_da_janela_estendida_segue_em_fail_open():
    row = _session(FAIL_OPEN_MAX_S - 1)
    sessions = FakeSessions(row)
    user = await _action(sessions, FakeClient(ExternalServiceUnavailableError("down"))).execute(RAW)
    assert user is not None and user.email == "ana@x.com"
    assert sessions.marked == []  # não finge que validou
    assert sessions.deleted == []


@pytest.mark.asyncio
async def test_plataforma_fora_alem_da_janela_estendida_propaga_unavailable():
    sessions = FakeSessions(_session(FAIL_OPEN_MAX_S))
    with pytest.raises(ExternalServiceUnavailableError):
        await _action(sessions, FakeClient(ExternalServiceUnavailableError("down"))).execute(RAW)
    assert sessions.deleted == []  # sessão fica; a plataforma é quem decide
```

- [ ] **Step 7: rodar e ver falhar**

Run: `uv run pytest tests/unit/domain/users/test_resolve_session_action.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 8: implementar `ResolveSessionAction`**

`src/domain/users/actions/resolve_session_action.py`:
```python
"""Cookie → sessão → identidade (ADR-0018, spec §2).

Valida a sessão contra a plataforma (`GET /api/users/profile`) com cache de
60s por sessão: banimento/revogação refletem em ≤60s. Se a plataforma está
fora (rede/5xx), segue em fail-open enquanto a última validação boa tiver
menos de 10min — depois disso propaga `ExternalServiceUnavailableError` (503),
para uma sessão não se validar sozinha para sempre.
"""

import logging
from datetime import datetime, timezone
from typing import Callable

from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.domain.users.services.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

PLATFORM_CHECK_TTL_S = 60
FAIL_OPEN_MAX_S = 600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResolveSessionAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()
        self.clock = clock or _utcnow

    async def execute(self, raw_token: str) -> AuthenticatedUser | None:
        """None = sem sessão válida (401 genérico no HTTP)."""
        session = await self.sessions.get_by_token_hash(hash_session_token(raw_token))
        if session is None:
            return None

        now = self.clock()
        age = session.seconds_since_platform_check(now)
        if age >= PLATFORM_CHECK_TTL_S:
            try:
                profile = await self.auth_client.get_profile(session.platform_access_token)
            except ExternalServiceUnavailableError:
                if age >= FAIL_OPEN_MAX_S:
                    raise
                logger.warning(
                    "plataforma indisponível; sessão segue em fail-open (%.0fs desde a última validação)",
                    age,
                )
            else:
                if profile is None:
                    # Expirada/revogada na plataforma: a nossa morre junto.
                    await self.sessions.delete(session.uuid)
                    return None
                await self.sessions.mark_platform_checked(session.uuid, now)

        return AuthenticatedUser(
            id=session.user_id,
            email=session.user_email,
            is_admin=session.user_email in settings.admin_emails,
            name=session.user_name,
            username=session.user_username,
        )
```

- [ ] **Step 9: rodar**

Run: `uv run pytest tests/unit/domain/users/test_resolve_session_action.py -v`
Expected: PASS (6)

- [ ] **Step 10: teste + implementação do `SignOutAction`**

`tests/unit/domain/users/test_sign_out_action.py`:
```python
"""SignOutAction (ADR-0018): signout na plataforma (best-effort) + apaga a sessão."""

from datetime import datetime, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.actions.sign_out_action import SignOutAction
from src.domain.users.entities.user_session import UserSession
from src.domain.users.services.session_tokens import hash_session_token

RAW = "token-cru"
NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
ROW = UserSession(
    uuid=uuid7(), token_hash=hash_session_token(RAW), platform_access_token="opaque-abc",
    user_id="u-1", user_email="ana@x.com", user_name=None, user_username=None,
    last_platform_check_at=NOW, created_at=NOW, updated_at=NOW,
)


class FakeSessions:
    def __init__(self, row):
        self.row, self.deleted = row, []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    def __init__(self):
        self.signed_out = []

    async def sign_out(self, access_token):
        self.signed_out.append(access_token)


@pytest.mark.asyncio
async def test_signout_na_plataforma_e_apaga_a_sessao():
    sessions, client = FakeSessions(ROW), FakeClient()
    await SignOutAction(auth_client=client, sessions=sessions).execute(RAW)
    assert client.signed_out == ["opaque-abc"]
    assert sessions.deleted == [ROW.uuid]


@pytest.mark.asyncio
async def test_sessao_desconhecida_e_noop():
    sessions, client = FakeSessions(None), FakeClient()
    await SignOutAction(auth_client=client, sessions=sessions).execute("outro")
    assert client.signed_out == []
    assert sessions.deleted == []
```

`src/domain/users/actions/sign_out_action.py`:
```python
"""Logout (ADR-0018): invalida na plataforma (best-effort — descartar só
localmente deixaria a sessão viva lá) e apaga a nossa linha."""

from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.domain.users.services.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient


class SignOutAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()

    async def execute(self, raw_token: str) -> None:
        session = await self.sessions.get_by_token_hash(hash_session_token(raw_token))
        if session is None:
            return
        await self.auth_client.sign_out(session.platform_access_token)  # nunca lança
        await self.sessions.delete(session.uuid)
```

`src/domain/users/actions/__init__.py`:
```python
from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.actions.sign_in_action import SignInAction
from src.domain.users.actions.sign_out_action import SignOutAction

__all__ = ["ResolveSessionAction", "SignInAction", "SignOutAction"]
```

- [ ] **Step 11: rodar os testes unitários de users**

Run: `uv run pytest tests/unit/domain/users -v`
Expected: PASS. (Os testes de integração de API estão quebrados neste ponto — `SignInResponse.from_result` ainda lê `access_token`; a Task 4 conserta.)

- [ ] **Step 12: commit**

```bash
git add src/domain/users tests/unit/domain/users
git commit -m "feat(auth): SignInAction v2 cria sessão; ResolveSessionAction (cache 60s + fail-open 10min); SignOutAction"
```

---

### Task 4: Camada HTTP — cookie, `require_user` v2, `/auth/login|me|logout`, fixtures de teste

**Files:**
- Create: `src/app/api/session_cookie.py`
- Modify: `src/app/api/dependencies/require_user.py` (reescrever)
- Modify: `src/app/api/controllers/auth_controller.py`, `src/app/api/routes/auth.py`, `src/app/api/responses/auth_responses.py`
- Modify: `src/app/api/routes/__init__.py` (só docstring: `public_router` hoje = `/health` e `POST /auth/login`)
- Modify: `tests/fakes/auth.py` (reescrever), `tests/conftest.py`
- Modify: `tests/unit/app/api/test_require_user.py` (reescrever), `tests/integration/api/test_auth_login.py` (reescrever)
- Modify (só `auth_headers` → `await auth_headers`): `tests/integration/api/test_conversation_endpoints.py`, `test_ops_endpoints.py`, `test_route_autodiscovery.py`, `test_ask_endpoint.py`, `test_ask_trace_persistence.py`

**Interfaces:**
- Consumes: `SignInAction`, `ResolveSessionAction`, `SignOutAction`, `AuthenticatedUser` (Task 3); `UserSessionRepository`, tokens (Task 1).
- Produces:
  - `SESSION_COOKIE_NAME = "ob_session"`, `set_session_cookie(response, token)`, `clear_session_cookie(response)`.
  - `require_user(request) -> AuthenticatedUser` (401 `not-authenticated` sem/inválido; 503 via handler quando fail-open estoura).
  - Rotas: `POST /auth/login` → 200 `{user:{id,email,name,username}, is_admin}` + `Set-Cookie`; `GET /auth/me` → mesmo shape; `POST /auth/logout` → 204 + cookie expirado.
  - Fixtures: `await seed_session(email, *, user_id, name, username, platform_token, checked_at) -> raw`, `cookie_headers(raw) -> {"Cookie": ...}`, `await auth_headers(email, **kw) -> {"Cookie": ...}`.

- [ ] **Step 1: cookie helper**

`src/app/api/session_cookie.py`:
```python
"""Cookie de sessão do oráculo (ADR-0018, spec §4.4).

HttpOnly (JS não lê), SameSite=Lax (bloqueia POST cross-site — é a proteção
CSRF; exige SPA e API no MESMO host), Secure fora de dev, Max-Age 7 dias
(mesma janela da plataforma; quem expira de verdade é ela).
"""

from fastapi import Response

from src.support.core.settings import settings

SESSION_COOKIE_NAME = "ob_session"
SESSION_COOKIE_MAX_AGE_S = 7 * 24 * 60 * 60


def _secure() -> bool:
    return settings.ENVIRONMENT != "development"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE_S,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure(),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=_secure()
    )
```

- [ ] **Step 2: testes do `require_user` v2**

Substituir `tests/unit/app/api/test_require_user.py` inteiro por:
```python
"""Guards (ADR-0018): cookie → ResolveSessionAction; 401 único em tudo que não
prova identidade; admin por allowlist (404)."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.core.context import CurrentRequestContext
from src.support.core.exceptions import ExternalServiceUnavailableError, NotFoundError
from src.support.core.settings import settings

ANA = AuthenticatedUser(id="u-1", email="ana@x.com", is_admin=False, name="Ana", username="ana")


def _request(cookie: str | None = None) -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


class FakeResolve:
    """Substitui ResolveSessionAction no módulo: registra o token recebido e
    devolve/lança o que o teste mandar."""

    seen: list[str] = []
    outcome = None

    def __init__(self, auth_client=None, **kw):
        pass

    async def execute(self, raw_token):
        FakeResolve.seen.append(raw_token)
        if isinstance(FakeResolve.outcome, Exception):
            raise FakeResolve.outcome
        return FakeResolve.outcome


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    import src.app.api.dependencies.require_user as mod

    FakeResolve.seen, FakeResolve.outcome = [], None
    monkeypatch.setattr(mod, "ResolveSessionAction", FakeResolve)
    yield
    CurrentRequestContext.clear()


@pytest.mark.asyncio
async def test_cookie_valido_devolve_user_e_preenche_o_contexto():
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = ANA
    user = await require_user(_request(f"{SESSION_COOKIE_NAME}=tok-123; outro=x"))
    assert user is ANA
    assert FakeResolve.seen == ["tok-123"]
    assert CurrentRequestContext.get_user() is ANA


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie", [None, "outro=x", f"{SESSION_COOKIE_NAME}=", f"{SESSION_COOKIE_NAME}=   "])
async def test_sem_cookie_de_sessao_da_401_sem_consultar_nada(cookie):
    from src.app.api.dependencies.require_user import require_user

    with pytest.raises(HTTPException) as exc:
        await require_user(_request(cookie))
    assert exc.value.status_code == 401
    assert exc.value.detail == "not-authenticated"
    assert FakeResolve.seen == []


@pytest.mark.asyncio
async def test_sessao_desconhecida_ou_revogada_da_401_generico():
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = None
    with pytest.raises(HTTPException) as exc:
        await require_user(_request(f"{SESSION_COOKIE_NAME}=nao-existe"))
    assert exc.value.status_code == 401
    assert exc.value.detail == "not-authenticated"
    assert CurrentRequestContext.get_user() is None


@pytest.mark.asyncio
async def test_plataforma_fora_alem_do_fail_open_propaga_unavailable():
    """Não é 401 (o usuário não fez nada errado): a exceção de domínio sobe e o
    exception handler traduz em 503 `unavailable`."""
    from src.app.api.dependencies.require_user import require_user

    FakeResolve.outcome = ExternalServiceUnavailableError("down")
    with pytest.raises(ExternalServiceUnavailableError):
        await require_user(_request(f"{SESSION_COOKIE_NAME}=tok"))


@pytest.mark.asyncio
async def test_require_admin_404_para_nao_admin(monkeypatch):
    from src.app.api.dependencies.require_admin import require_admin

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "admin@x.com")
    with pytest.raises(NotFoundError):
        await require_admin(AuthenticatedUser(id="u", email="a@x.com", is_admin=False))
    admin = AuthenticatedUser(id="u", email="admin@x.com", is_admin=True)
    assert await require_admin(admin) is admin
```

- [ ] **Step 3: rodar e ver falhar**

Run: `uv run pytest tests/unit/app/api/test_require_user.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'ResolveSessionAction'` / import de `session_cookie` ok após o Step 1)

- [ ] **Step 4: reescrever `require_user`**

Substituir `src/app/api/dependencies/require_user.py` inteiro por:
```python
"""Identidade por request (ADR-0018): cookie `ob_session` → sessão → validação
na plataforma (cache 60s / fail-open 10min) → AuthenticatedUser no contexto.

O 401 é único e indistinguível (sem cookie, cookie desconhecido, sessão
revogada). Plataforma fora além do fail-open NÃO é 401: a
`ExternalServiceUnavailableError` sobe e o handler responde 503.
"""

from fastapi import HTTPException, Request

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.context import CurrentRequestContext


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="not-authenticated")


async def require_user(request: Request) -> AuthenticatedUser:
    raw_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if not raw_token:
        raise _unauthorized()

    user = await ResolveSessionAction(auth_client=BorderlessAuthClient()).execute(raw_token)
    if user is None:
        raise _unauthorized()

    CurrentRequestContext.set_user(user)
    return user
```

- [ ] **Step 5: rodar**

Run: `uv run pytest tests/unit/app/api/test_require_user.py -v`
Expected: PASS (8)

- [ ] **Step 6: responses, controller, rotas**

Substituir `src/app/api/responses/auth_responses.py` inteiro por:
```python
from pydantic import BaseModel

from src.domain.users.dtos.sign_in_result import SignInResult
from src.domain.users.entities.authenticated_user import AuthenticatedUser


class AuthUserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    username: str | None


class SessionResponse(BaseModel):
    """Shape único de `POST /auth/login` e `GET /auth/me`. NUNCA carrega token:
    a credencial vai no cookie httpOnly (ADR-0018)."""

    user: AuthUserResponse
    is_admin: bool

    @classmethod
    def from_result(cls, result: SignInResult) -> "SessionResponse":
        return cls(
            user=AuthUserResponse(
                id=result.user.id,
                email=result.user.email,
                name=result.user.name,
                username=result.user.username,
            ),
            is_admin=result.is_admin,
        )

    @classmethod
    def from_authenticated_user(cls, user: AuthenticatedUser) -> "SessionResponse":
        return cls(
            user=AuthUserResponse(id=user.id, email=user.email, name=user.name, username=user.username),
            is_admin=user.is_admin,
        )
```

Substituir `src/app/api/controllers/auth_controller.py` inteiro por:
```python
from fastapi import Depends, Request, Response

from src.app.api.dependencies.require_user import require_user
from src.app.api.requests.sign_in_request import SignInRequest
from src.app.api.responses.auth_responses import SessionResponse
from src.app.api.session_cookie import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    set_session_cookie,
)
from src.domain.users.actions.sign_in_action import SignInAction
from src.domain.users.actions.sign_out_action import SignOutAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient


class AuthController:
    @staticmethod
    async def login(data: SignInRequest, response: Response) -> SessionResponse:
        action = SignInAction(auth_client=BorderlessAuthClient())
        result = await action.execute(data.email, data.password)
        set_session_cookie(response, result.session_token)
        return SessionResponse.from_result(result)

    @staticmethod
    async def me(user: AuthenticatedUser = Depends(require_user)) -> SessionResponse:
        # Só projeção do snapshot da sessão — sem Action (spec §4.3).
        return SessionResponse.from_authenticated_user(user)

    @staticmethod
    async def logout(request: Request) -> Response:
        raw_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
        if raw_token:
            await SignOutAction(auth_client=BorderlessAuthClient()).execute(raw_token)
        response = Response(status_code=204)
        clear_session_cookie(response)
        return response
```

Substituir `src/app/api/routes/auth.py` inteiro por:
```python
"""Auth (ADR-0018). `POST /auth/login` é público (bridge com a plataforma);
`/auth/me` e `/auth/logout` ficam no `router` — o autodiscovery amarra
`require_user` mecanicamente."""

from fastapi import APIRouter

from src.app.api.controllers.auth_controller import AuthController

public_router = APIRouter(prefix="/auth", tags=["Auth"])
public_router.post("/login")(AuthController.login)

router = APIRouter(prefix="/auth", tags=["Auth"])
router.get("/me")(AuthController.me)
router.post("/logout", status_code=204)(AuthController.logout)
```

Em `src/app/api/routes/__init__.py`, na docstring, trocar `(ADR-0017, fail-closed)` por `(ADR-0017/0018, fail-closed)` — o restante da docstring já está correto (`/health` e `POST /auth/login` são os únicos públicos).

- [ ] **Step 7: fixtures de teste — `tests/fakes/auth.py` e `tests/conftest.py`**

Substituir `tests/fakes/auth.py` inteiro por:
```python
"""Sessões de teste (ADR-0018).

`seed_session` grava uma linha em `sessions` já validada (`last_platform_check_at`
= agora → dentro do cache de 60s, o `require_user` NÃO vai à plataforma) e
devolve o token CRU; `cookie_headers` monta o header `Cookie` que o SPA
mandaria. Tudo que foi semeado é apagado no fim da sessão de testes
(`purge_seeded_sessions`, chamado pelo conftest).
"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.domain.users.services.session_tokens import generate_session_token, hash_session_token
from src.support.core.session_scope import run_in_async_session
from src.support.core.settings import settings

_SEEDED_HASHES: list[str] = []


async def seed_session(
    email: str,
    *,
    user_id: str = "user-1",
    name: str | None = None,
    username: str | None = None,
    platform_token: str = "plat-token-teste",
    checked_at: datetime | None = None,
) -> str:
    raw = generate_session_token()
    token_hash = hash_session_token(raw)
    now = datetime.now(timezone.utc)

    async def _work():
        await UserSessionRepository().create(
            UserSession(
                uuid=uuid7(),
                token_hash=token_hash,
                platform_access_token=platform_token,
                user_id=user_id,
                user_email=email.strip().lower(),
                user_name=name,
                user_username=username,
                last_platform_check_at=checked_at or now,
                created_at=now,
                updated_at=now,
            )
        )

    await run_in_async_session(_work)
    _SEEDED_HASHES.append(token_hash)
    return raw


def cookie_headers(raw_token: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={raw_token}"}


async def auth_headers(email: str, **kw) -> dict[str, str]:
    """Substituto direto do `auth_headers` da v1 — agora assíncrono."""
    return cookie_headers(await seed_session(email, **kw))


async def purge_seeded_sessions() -> None:
    """Engine própria (o `engine` global pode estar preso a um loop já fechado)."""
    if not _SEEDED_HASHES:
        return
    engine = create_async_engine(settings.database_url_async, poolclass=None)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession)
    try:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM sessions WHERE token_hash = ANY(:hashes)"),
                {"hashes": list(_SEEDED_HASHES)},
            )
            await session.commit()
    finally:
        await engine.dispose()
        _SEEDED_HASHES.clear()
```

Substituir `tests/conftest.py` inteiro por:
```python
"""Configuração global de testes."""

import asyncio
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Configura variáveis de ambiente para testes."""
    # Dummy API key para testes unitários — não faz chamadas reais.
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "sk-test-dummy-key"
    if not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-dummy-key"

    yield

    # Sessões semeadas por tests/fakes/auth.py (ADR-0018) não podem acumular
    # no banco de dev entre execuções.
    from tests.fakes.auth import purge_seeded_sessions

    asyncio.run(purge_seeded_sessions())
```

- [ ] **Step 8: atualizar os testes de integração que usavam `auth_headers` síncrono**

Em cada arquivo, a mudança é mecânica: `auth_headers(x)` → `await auth_headers(x)` (o helper agora é `async`). Ocorrências:

`tests/integration/api/test_conversation_endpoints.py`:
- linha `headers = auth_headers(email)` → `headers = await auth_headers(email)`
- `headers=auth_headers("qualquer@x.com")` → `headers=await auth_headers("qualquer@x.com")`
- `headers=auth_headers("intrusa@x.com")` → `headers=await auth_headers("intrusa@x.com")`
- docstring do `test_sem_token_tudo_da_401` pode ficar; renomear para `test_sem_cookie_tudo_da_401`.

`tests/integration/api/test_ops_endpoints.py`:
- na fixture `ops_client`: `headers=auth_headers("admin@x.com")` → `headers=await auth_headers("admin@x.com")` (a fixture já é `async`).
- `test_ops_para_nao_admin_da_404`: `headers=auth_headers("comum@x.com")` → `headers=await auth_headers("comum@x.com")`.
- renomear `test_ops_sem_token_da_401` → `test_ops_sem_cookie_da_401`.

`tests/integration/api/test_route_autodiscovery.py`:
- `com_token = await client.get("/dummy-hipotetico", headers=auth_headers("a@x.com"))` → `headers=await auth_headers("a@x.com")`.
- docstring do módulo: `(ADR-0017)` → `(ADR-0017/0018)`.

`tests/integration/api/test_ask_endpoint.py` (3 ocorrências) e `tests/integration/api/test_ask_trace_persistence.py` (3 ocorrências): `headers=auth_headers("asker@x.com")` → `headers=await auth_headers("asker@x.com")`.

Verificar que nada ficou para trás:
```bash
grep -rn "auth_headers(" tests | grep -v "await auth_headers\|def auth_headers"
```
Expected: nenhuma linha.

- [ ] **Step 9: reescrever o teste de integração de `/auth/*`**

Substituir `tests/integration/api/test_auth_login.py` inteiro por:
```python
"""POST /auth/login, GET /auth/me, POST /auth/logout — BFF (ADR-0018).
Plataforma mockada nos dois pontos de uso (controller e require_user)."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.app.api.session_cookie import SESSION_COOKIE_NAME
from src.domain.users.services.session_tokens import hash_session_token
from src.support.clients.borderless.borderless_auth_client import (
    PlatformProfile,
    PlatformSignIn,
    PlatformUser,
)
from src.support.core.exceptions import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidCredentialsError,
)
from src.support.core.settings import settings
from tests.fakes.auth import auth_headers, cookie_headers, seed_session


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    yield
    from src.support.core.database import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def api_client():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class FakePlatform:
    """Uma classe só, instanciada pelo controller E pelo require_user; o estado
    fica em atributos de classe para o teste inspecionar."""

    signed_out: list[str] = []
    profile_calls: list[str] = []
    sign_in_error: Exception | None = None
    profile_outcome = "ok"  # "ok" | None (401) | "down"

    @classmethod
    def reset(cls):
        cls.signed_out, cls.profile_calls, cls.sign_in_error, cls.profile_outcome = [], [], None, "ok"

    def __init__(self, transport=None):
        pass

    async def sign_in(self, email, password):
        if FakePlatform.sign_in_error:
            raise FakePlatform.sign_in_error
        return PlatformSignIn(
            user=PlatformUser(id="u-1", email=email, name="Ana", username="ana",
                              career_stage="junior_transition", email_verified=True),
            access_token="plat-abc",
            expires_in=604800,
        )

    async def get_profile(self, access_token):
        FakePlatform.profile_calls.append(access_token)
        if FakePlatform.profile_outcome == "down":
            raise ExternalServiceUnavailableError("down")
        if FakePlatform.profile_outcome is None:
            return None
        return PlatformProfile(id="u-1", email="ana@x.com", name="Ana", username="ana",
                               membership="BASE", community_role="MEMBER")

    async def sign_out(self, access_token):
        FakePlatform.signed_out.append(access_token)


@pytest.fixture(autouse=True)
def _fake_platform(monkeypatch):
    import src.app.api.controllers.auth_controller as ctrl
    import src.app.api.dependencies.require_user as dep

    FakePlatform.reset()
    monkeypatch.setattr(ctrl, "BorderlessAuthClient", FakePlatform)
    monkeypatch.setattr(dep, "BorderlessAuthClient", FakePlatform)


def _unique_email() -> str:
    # E-mail único por execução: o rate limit do login é REAL (tabela
    # rate_limits) e acumularia entre rodadas da suíte.
    return f"ana-{uuid4().hex[:8]}@x.com"


async def _session_row(raw_token: str) -> dict | None:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                text("SELECT platform_access_token, user_email FROM sessions WHERE token_hash = :h"),
                {"h": hash_session_token(raw_token)},
            )
        ).mappings().first()
        return dict(row) if row else None


async def _delete_session_row(raw_token: str) -> None:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await s.execute(text("DELETE FROM sessions WHERE token_hash = :h"), {"h": hash_session_token(raw_token)})
        await s.commit()


@pytest.mark.asyncio
async def test_login_seta_cookie_httponly_cria_sessao_e_nao_expoe_token(api_client, monkeypatch):
    email = _unique_email()
    monkeypatch.setattr(settings, "ADMIN_EMAILS", email)

    resp = await api_client.post("/auth/login", json={"email": email.upper(), "password": "s3nh4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "user": {"id": "u-1", "email": email, "name": "Ana", "username": "ana"},
        "is_admin": True,
    }
    assert "plat-abc" not in resp.text

    set_cookie = resp.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "max-age=604800" in set_cookie
    assert "secure" not in set_cookie  # ENVIRONMENT=development

    raw = api_client.cookies.get(SESSION_COOKIE_NAME)
    assert raw
    row = await _session_row(raw)
    assert row == {"platform_access_token": "plat-abc", "user_email": email}

    await _delete_session_row(raw)


@pytest.mark.asyncio
async def test_login_me_logout_fim_a_fim(api_client):
    email = _unique_email()
    login = await api_client.post("/auth/login", json={"email": email, "password": "s3nh4"})
    assert login.status_code == 200
    raw = api_client.cookies.get(SESSION_COOKIE_NAME)

    # /auth/me com o cookie que o client guardou (dentro do cache → sem ida à plataforma)
    me = await api_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email
    assert FakePlatform.profile_calls == []

    logout = await api_client.post("/auth/logout")
    assert logout.status_code == 204
    assert FakePlatform.signed_out == ["plat-abc"]
    assert "max-age=0" in logout.headers["set-cookie"].lower() or "expires=" in logout.headers["set-cookie"].lower()
    assert await _session_row(raw) is None

    # O cookie antigo não vale mais nada.
    depois = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert depois.status_code == 401


@pytest.mark.asyncio
async def test_me_sem_cookie_da_401(api_client):
    resp = await api_client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "not-authenticated"


@pytest.mark.asyncio
async def test_logout_sem_cookie_e_204_idempotente(api_client):
    assert (await api_client.post("/auth/logout")).status_code == 204
    assert FakePlatform.signed_out == []


@pytest.mark.asyncio
async def test_login_invalido_devolve_401_com_codigo_estavel(api_client):
    FakePlatform.sign_in_error = InvalidCredentialsError("nope")
    resp = await api_client.post("/auth/login", json={"email": _unique_email(), "password": "errada"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid-credentials"}
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_login_forbidden_repassa_a_message_da_plataforma(api_client):
    FakePlatform.sign_in_error = ForbiddenError("Sua conta está desativada.")
    resp = await api_client.post("/auth/login", json={"email": _unique_email(), "password": "s"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "forbidden", "message": "Sua conta está desativada."}


@pytest.mark.asyncio
async def test_sessao_fora_do_cache_e_revogada_na_plataforma_da_401_e_apaga(api_client):
    FakePlatform.profile_outcome = None  # plataforma diz 401
    stale = datetime.now(timezone.utc) - timedelta(minutes=2)
    raw = await seed_session("ana@x.com", platform_token="plat-velho", checked_at=stale)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 401
    assert FakePlatform.profile_calls == ["plat-velho"]
    assert await _session_row(raw) is None


@pytest.mark.asyncio
async def test_sessao_fora_do_cache_valida_na_plataforma_e_renova_o_carimbo(api_client):
    stale = datetime.now(timezone.utc) - timedelta(minutes=2)
    raw = await seed_session("ana@x.com", platform_token="plat-ok", checked_at=stale)

    primeira = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert primeira.status_code == 200
    segunda = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert segunda.status_code == 200
    assert FakePlatform.profile_calls == ["plat-ok"]  # a segunda veio do cache


@pytest.mark.asyncio
async def test_plataforma_fora_alem_do_fail_open_da_503(api_client):
    FakePlatform.profile_outcome = "down"
    muito_velha = datetime.now(timezone.utc) - timedelta(minutes=11)
    raw = await seed_session("ana@x.com", checked_at=muito_velha)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 503
    assert resp.json() == {"detail": "unavailable"}


@pytest.mark.asyncio
async def test_plataforma_fora_dentro_do_fail_open_segue(api_client):
    FakePlatform.profile_outcome = "down"
    recente = datetime.now(timezone.utc) - timedelta(minutes=5)
    raw = await seed_session("ana@x.com", checked_at=recente)

    resp = await api_client.get("/auth/me", headers=cookie_headers(raw))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_conversations_com_cookie_semeado_passa(api_client):
    resp = await api_client.get("/conversations", headers=await auth_headers("ana@x.com"))
    assert resp.status_code == 200
```

- [ ] **Step 10: rodar a suíte de API e os unitários**

Run: `uv run pytest tests/unit tests/integration/api -q`
Expected: PASS. Se `test_login_me_logout_fim_a_fim` falhar na asserção do `set-cookie` do logout, imprima `logout.headers["set-cookie"]` e ajuste a asserção ao que o Starlette emite (`Max-Age=0` + `expires=`), sem afrouxar o resto.

- [ ] **Step 11: commit**

```bash
git add src/app/api tests/fakes/auth.py tests/conftest.py tests/unit/app/api/test_require_user.py tests/integration/api
git commit -m "feat(auth): BFF — cookie ob_session, require_user por sessão, /auth/me e /auth/logout; fixtures de sessão nos testes"
```

---

### Task 5: Limpeza da v1 — `pyjwt`, envs, CORS, docs

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv remove`)
- Modify: `src/support/core/settings.py`, `.env.example`, `main.py`
- Modify: `tests/unit/app/test_settings_auth.py`
- Modify: `CLAUDE.md`, `docs/autenticacao.md`

- [ ] **Step 1: teste de settings v2**

Substituir `tests/unit/app/test_settings_auth.py` inteiro por:
```python
"""Settings de auth (ADR-0017/0018): defaults, allowlist e ausência das envs mortas."""

from src.support.core.settings import Settings


def test_auth_settings_defaults():
    s = Settings(_env_file=None)
    assert s.BORDERLESS_AUTH_URL == "https://api.borderlesscoding.com"
    assert s.ADMIN_EMAILS == ""
    assert s.admin_emails == frozenset()


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
```

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/unit/app/test_settings_auth.py -v`
Expected: FAIL em `test_envs_da_v1_nao_existem_mais`

- [ ] **Step 3: settings + .env.example + main.py**

Em `src/support/core/settings.py`, substituir o bloco de auth por:
```python
    # --- Autenticação: plataforma Borderless como IdP, BFF (ADR-0017/0018) ---
    # Login é público (sem key de app) e o accessToken é opaco: não há nada de
    # JWT para configurar. TTL do cache de validação e janela de fail-open são
    # constantes em ResolveSessionAction (virar env só se precisar calibrar).
    BORDERLESS_AUTH_URL: str = "https://api.borderlesscoding.com"
    ADMIN_EMAILS: str = ""  # allowlist de admins do /ops, separada por vírgula
```
e o comentário do CORS por:
```python
    # --- CORS ---
    # Vazio (default) = SPA e API no mesmo host (proxy do Vite em dev) e nenhum
    # CORSMiddleware é montado. A sessão é cookie SameSite=Lax (ADR-0018):
    # split-host exigiria SameSite=None + CSRF token — fora da v2. Este campo
    # segue só para o caso same-site com subdomínios, sem credentials.
    CORS_ORIGINS: str = ""  # origens separadas por vírgula, ex.: https://app.borderlesscoding.com
```

Em `.env.example`, substituir o bloco de auth por:
```
# --- Autenticação (ADR-0017/0018) ---
# Login é público e o token da plataforma é opaco: nenhum segredo necessário.
BORDERLESS_AUTH_URL=https://api.borderlesscoding.com
ADMIN_EMAILS=
```

Em `main.py`, trocar o comentário `allow_credentials=False,  # Bearer, não cookie — sem necessidade de credentials` por `allow_credentials=False,  # cookie SameSite=Lax exige mesmo host; sem credentials cross-origin (ADR-0018)`.

- [ ] **Step 4: remover `pyjwt`**

```bash
uv remove pyjwt
grep -n "pyjwt\|jwt" pyproject.toml uv.lock | head
grep -rn "import jwt" src tests
```
Expected: nenhuma ocorrência em `pyproject.toml`/`src`/`tests` (o `uv.lock` pode manter `cryptography` se outra dep a usa — ok). Ajustar o comentário acima de `"httpx>=0.27"` em `pyproject.toml` para `# Autenticação (ADR-0018): bridge BFF com a plataforma`.

- [ ] **Step 5: docs**

`CLAUDE.md`, linha da stack **Autenticação** — substituir por:
```
- **Autenticação:** plataforma Borderless como IdP via **BFF**: `POST /auth/login` (público, sem key) chama o signin da plataforma, guarda o `accessToken` **opaco** na tabela `sessions` e devolve cookie httpOnly `ob_session`; `require_user` resolve cookie → sessão → valida na plataforma (`GET /api/users/profile`, cache 60s, fail-open ≤10min); `GET /auth/me` restaura, `POST /auth/logout` revoga. Admin do `/ops` por allowlist `ADMIN_EMAILS` (404 para os demais). **Não há Keycloak/OpenFGA/Supabase nem JWT neste projeto.** Ver ADR-0017, ADR-0018 e `docs/autenticacao.md`.
```
Na lista "ADRs atuais", trocar a linha do 0017 por:
```
- **ADR-0017** — Plataforma Borderless como IdP; sem Supabase (validação/sessão substituídas pelo 0018)
- **ADR-0018** — Auth vira BFF: token opaco da plataforma vive só no servidor; cookie httpOnly; `pyjwt` removido
```

`docs/autenticacao.md` — substituir o parágrafo de **Status** (as primeiras linhas até antes do `---` do §0) por:
```
**Status:** v2 (BFF) **implementada em 2026-09-04** na branch `feat/autenticacao`,
conforme o ADR-0018. O §0 abaixo registra o delta que foi aplicado sobre a v1
(ADR-0017), para leitura histórica; o restante do documento descreve o que o
código faz hoje. Contrato da plataforma verificado em `autenticacao_plataform.md`.
```
No §9 e §11, marcar os checkboxes concluídos com `[x]` (deixar `[ ]` só em "Validar o contrato manualmente" se a Task 0 não rodou).

- [ ] **Step 6: verificação**

```bash
uv run pytest tests/unit -q
uv run python -c "from main import app; print('OK')"
uv run alembic check
```
Expected: tudo PASS / OK / "No new upgrade operations detected."

- [ ] **Step 7: commit**

```bash
git add pyproject.toml uv.lock src/support/core/settings.py .env.example main.py tests/unit/app/test_settings_auth.py CLAUDE.md docs/autenticacao.md
git commit -m "chore(auth): remove pyjwt e envs da v1; docs descrevem o BFF (ADR-0018)"
```

---

### Task 6: Frontend — `useAuth` v2 (restore via `/auth/me`), sem `session.ts`/Bearer

**Files:**
- Delete: `frontend/src/lib/auth/session.ts`, `frontend/src/lib/auth/session.test.ts`
- Modify: `frontend/src/lib/api/client.ts`, `frontend/src/lib/api/conversations.ts`, `frontend/src/hooks/useAuth.tsx`, `frontend/vite.config.ts`
- Create: `frontend/src/test/authFetch.ts`
- Test: `frontend/src/hooks/useAuth.test.tsx` (reescrever)

**Interfaces:**
- Produces:
  - `useAuth(): { user: AuthUser | null; isAdmin; status: "loading"|"ready"|"error"; login(email, password): Promise<LoginError | null>; logout(): Promise<void>; retry(): void }`.
  - `AuthUser { id; email; name: string|null; username: string|null }`; `LoginError { code: "invalid-credentials"|"rate-limited"|"forbidden"|"unavailable"; message?: string }`.
  - `stubAuthFetch(me, fallback?)` em `src/test/authFetch.ts` — devolve o mock de `fetch` com `.setMe(next)`; `loggedIn(isAdmin=false)`; `TEST_USER`.

- [ ] **Step 1: apagar `session.ts` e cortar o Bearer do client**

```bash
git rm frontend/src/lib/auth/session.ts frontend/src/lib/auth/session.test.ts
```

Substituir `frontend/src/lib/api/client.ts` inteiro por:
```ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${BASE}${path}`;
}

/** 401 em qualquer chamada = sessão inválida/expirada/revogada (ADR-0018):
 * volta ao login preservando a rota. Não há storage a limpar — a credencial
 * é o cookie httpOnly, que o backend já invalidou. */
export function handleUnauthorized(): void {
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

/** fetch same-origin leva o cookie `ob_session` sozinho — nada de header. */
export async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(apiUrl(path));
  if (resp.status === 401) {
    handleUnauthorized();
    throw new Error("não autenticado");
  }
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  return (await resp.json()) as T;
}
```

Em `frontend/src/lib/api/conversations.ts`:
- import: `import { apiUrl, getJSON, handleUnauthorized } from "./client";`
- em `askStream`: `headers: { "Content-Type": "application/json" },` (remover `...authHeaders()`).

Em `frontend/vite.config.ts`, no `proxy`, logo após `"/auth/login": "http://localhost:8000",` adicionar:
```ts
      "/auth/me": "http://localhost:8000",
      "/auth/logout": "http://localhost:8000",
```

- [ ] **Step 2: helper de teste**

`frontend/src/test/authFetch.ts`:
```ts
import { vi } from "vitest";

/** Sessão fake respondida por GET /auth/me (ADR-0018: o SPA não tem storage
 * de sessão — a única fonte de identidade é esse endpoint). */
export const TEST_USER = { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" };

export type MeOutcome =
  | { user: typeof TEST_USER; is_admin: boolean } // 200
  | 401 // deslogado
  | "network"; // falha de rede → status "error" no AuthProvider

export const loggedIn = (isAdmin = false): MeOutcome => ({ user: TEST_USER, is_admin: isAdmin });

type Fallback = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Stub global de `fetch` que resolve /auth/me e /auth/logout e delega o resto
 * a `fallback` (default: `[]` com 200). `setMe` troca o desfecho do /auth/me
 * no meio do teste (ex.: rede volta → retry). */
export function stubAuthFetch(me: MeOutcome, fallback?: Fallback) {
  const state = { me };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/auth/me")) {
      if (state.me === "network") throw new Error("down");
      if (state.me === 401) {
        return new Response(JSON.stringify({ detail: "not-authenticated" }), { status: 401 });
      }
      return new Response(JSON.stringify(state.me), { status: 200 });
    }
    if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
    if (fallback) return fallback(url, init);
    return new Response(JSON.stringify([]), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return Object.assign(fetchMock, {
    setMe(next: MeOutcome) {
      state.me = next;
    },
  });
}
```

- [ ] **Step 3: testes do `useAuth` v2**

Substituir `frontend/src/hooks/useAuth.test.tsx` inteiro por:
```tsx
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth, type LoginError } from "./useAuth";
import { loggedIn, stubAuthFetch, TEST_USER } from "../test/authFetch";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), { status });

describe("useAuth — restore via /auth/me", () => {
  it("200 popula user e isAdmin", async () => {
    const fetchMock = stubAuthFetch(loggedIn(true));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user).toEqual(TEST_USER);
    expect(result.current.isAdmin).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/auth\/me$/));
  });

  it("401 = deslogado (ready, sem user)", async () => {
    stubAuthFetch(401);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user).toBeNull();
    expect(result.current.isAdmin).toBe(false);
  });

  it("falha de rede vira status 'error' (terceiro estado) e retry recupera", async () => {
    const fetchMock = stubAuthFetch("network");
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.user).toBeNull();

    fetchMock.setMe(loggedIn());
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.user?.email).toBe("ana@x.com");
  });

  it("5xx no /auth/me também é 'error', não deslogado", async () => {
    stubAuthFetch(401, () => json({ detail: "unavailable" }, 503));
    // força o /auth/me a cair no fallback 503:
    const fetchMock = vi.fn(async () => json({ detail: "unavailable" }, 503));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("error"));
  });
});

describe("useAuth — login", () => {
  it("ok: popula user/isAdmin e devolve null (sem token no corpo)", async () => {
    stubAuthFetch(401, () => json({ user: TEST_USER, is_admin: false }, 200));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = { code: "unavailable" };
    await act(async () => {
      err = await result.current.login("ana@x.com", "s3nh4");
    });
    expect(err).toBeNull();
    expect(result.current.user).toEqual(TEST_USER);
    expect(result.current.isAdmin).toBe(false);
  });

  it("inválido devolve o código estável e não popula", async () => {
    stubAuthFetch(401, () => json({ detail: "invalid-credentials" }, 401));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "errada");
    });
    expect(err).toEqual({ code: "invalid-credentials" });
    expect(result.current.user).toBeNull();
  });

  it("forbidden carrega a message da plataforma", async () => {
    stubAuthFetch(401, () =>
      json({ detail: "forbidden", message: "Sua conta está desativada." }, 403)
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s");
    });
    expect(err).toEqual({ code: "forbidden", message: "Sua conta está desativada." });
  });

  it("200 com corpo fora do contrato vira 'unavailable' em vez de lançar", async () => {
    stubAuthFetch(401, () => json({}, 200));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s3nh4");
    });
    expect(err).toEqual({ code: "unavailable" });
    expect(result.current.user).toBeNull();
  });

  it("falha de rede vira 'unavailable'", async () => {
    stubAuthFetch(401, () => {
      throw new Error("down");
    });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    let err: LoginError | null = null;
    await act(async () => {
      err = await result.current.login("a@x.com", "s");
    });
    expect(err).toEqual({ code: "unavailable" });
  });
});

describe("useAuth — logout", () => {
  it("zera o estado e chama POST /auth/logout", async () => {
    const fetchMock = stubAuthFetch(loggedIn());
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());
    await act(async () => {
      await result.current.logout();
    });
    expect(result.current.user).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/logout$/),
      expect.objectContaining({ method: "POST" })
    );
  });
});
```

- [ ] **Step 4: rodar e ver falhar**

Run: `cd frontend && npx vitest run src/hooks/useAuth.test.tsx`
Expected: FAIL (import de `../lib/auth/session` quebrado / `LoginError` inexistente)

- [ ] **Step 5: reescrever `useAuth.tsx`**

Substituir `frontend/src/hooks/useAuth.tsx` inteiro por:
```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiUrl } from "../lib/api/client";

const DEMO = import.meta.env.VITE_DEMO_MODE === "true";

/** Identidade do usuário logado (ADR-0018). O SPA NÃO guarda credencial: a
 * sessão é o cookie httpOnly `ob_session`, que o browser manda sozinho. Este
 * estado vive só em memória e é restaurado por GET /auth/me a cada boot.
 * isAdmin aqui é SÓ UI — o backend recalcula e responde 404. */
export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  username: string | null;
}

export type LoginErrorCode = "invalid-credentials" | "rate-limited" | "forbidden" | "unavailable";

/** `message` só vem em `forbidden`: é a mensagem da plataforma, voltada ao
 * usuário (única exceção à regra "nunca o erro cru" — spec §3). */
export interface LoginError {
  code: LoginErrorCode;
  message?: string;
}

type AuthStatus = "loading" | "ready" | "error";

type AuthSession = { user: AuthUser; isAdmin: boolean };

type AuthContextValue = {
  user: AuthUser | null;
  isAdmin: boolean;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<LoginError | null>;
  logout: () => Promise<void>;
  retry: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const DEMO_SESSION: AuthSession = {
  user: { id: "demo", email: "demo@borderless.dev", name: "Demo", username: "demo" },
  isAdmin: true,
};

/** Lança se o corpo não bate com o contrato de /auth/login e /auth/me. */
function parseSession(body: unknown): AuthSession {
  const b = body as { user?: Partial<AuthUser>; is_admin?: unknown } | null;
  if (!b || !b.user || typeof b.user.id !== "string" || typeof b.user.email !== "string") {
    throw new Error("sessão fora do contrato");
  }
  return {
    user: {
      id: b.user.id,
      email: b.user.email,
      name: b.user.name ?? null,
      username: b.user.username ?? null,
    },
    isAdmin: b.is_admin === true,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const restore = useCallback(async () => {
    if (DEMO) {
      setSession(DEMO_SESSION);
      setStatus("ready");
      return;
    }
    setStatus("loading");
    let resp: Response;
    try {
      resp = await fetch(apiUrl("/auth/me"));
    } catch {
      // Rede fora: NÃO é "deslogado" — terceiro estado com retry (spec §5).
      setStatus("error");
      return;
    }
    if (resp.status === 401) {
      setSession(null);
      setStatus("ready");
      return;
    }
    if (!resp.ok) {
      setStatus("error");
      return;
    }
    try {
      setSession(parseSession(await resp.json()));
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void restore();
  }, [restore]);

  const login = useCallback(async (email: string, password: string): Promise<LoginError | null> => {
    let resp: Response;
    try {
      resp = await fetch(apiUrl("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      return { code: "unavailable" };
    }
    if (!resp.ok) {
      const body = (await resp.json().catch(() => null)) as
        | { detail?: unknown; message?: unknown }
        | null;
      const detail = body?.detail;
      if (detail === "invalid-credentials" || detail === "rate-limited") return { code: detail };
      if (detail === "forbidden") {
        return {
          code: "forbidden",
          message: typeof body?.message === "string" ? body.message : undefined,
        };
      }
      return { code: "unavailable" };
    }
    // 200 não garante o contrato (proxy devolvendo HTML, corpo sem `user`):
    // sem este guard a exceção do parse deixava o form preso em "Entrando…".
    try {
      setSession(parseSession(await resp.json()));
      setStatus("ready");
      return null;
    } catch {
      return { code: "unavailable" };
    }
  }, []);

  const logout = useCallback(async () => {
    setSession(null);
    if (DEMO) return;
    try {
      await fetch(apiUrl("/auth/logout"), { method: "POST" });
    } catch {
      // Estado local já foi; o backend revoga na plataforma quando alcançável
      // e a sessão da plataforma expira sozinha em 7 dias.
    }
  }, []);

  const retry = useCallback(() => {
    void restore();
  }, [restore]);

  const value = useMemo(
    () => ({
      user: session?.user ?? null,
      isAdmin: session?.isAdmin ?? false,
      status,
      login,
      logout,
      retry,
    }),
    [session, status, login, logout, retry]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de <AuthProvider>");
  return context;
}
```

- [ ] **Step 6: rodar**

Run: `cd frontend && npx vitest run src/hooks/useAuth.test.tsx`
Expected: PASS (10). Os outros arquivos de teste (App, RequireAuth, Sidebar, LoginPage) ainda importam `lib/auth/session` e quebram — a Task 7 conserta.

- [ ] **Step 7: commit**

```bash
git add frontend/src/lib frontend/src/hooks/useAuth.tsx frontend/src/hooks/useAuth.test.tsx frontend/src/test/authFetch.ts frontend/vite.config.ts
git commit -m "feat(frontend/auth): useAuth v2 — restore via /auth/me, logout via /auth/logout, sem localStorage/Bearer (ADR-0018)"
```

---

### Task 7: Frontend — `forbidden` no login, logout assíncrono, testes de App/RequireAuth/Sidebar/LoginPage

**Files:**
- Modify: `frontend/src/features/auth/LoginPage.tsx`, `frontend/src/components/AuthSettings/AuthSettings.tsx`
- Modify (testes): `frontend/src/features/auth/LoginPage.test.tsx`, `frontend/src/components/RequireAuth/RequireAuth.test.tsx`, `frontend/src/App.test.tsx`, `frontend/src/features/chat/components/Sidebar.test.tsx`

**Interfaces:**
- Consumes: `useAuth().login -> LoginError | null`, `useAuth().logout(): Promise<void>` (Task 6); `stubAuthFetch`, `loggedIn`, `TEST_USER` (Task 6).

- [ ] **Step 1: LoginPage — `forbidden` mostra a mensagem da plataforma**

Em `frontend/src/features/auth/LoginPage.tsx`:

`ERROR_MESSAGES` ganha uma entrada (fallback, caso a plataforma não mande `message`):
```ts
const ERROR_MESSAGES: Record<string, string> = {
  "invalid-credentials": "E-mail ou senha inválidos.",
  "rate-limited": "Muitas tentativas. Aguarde alguns minutos e tente de novo.",
  forbidden: "Sua conta não pode acessar o oráculo no momento.",
  unavailable: "Não foi possível falar com a plataforma. Tente novamente em instantes.",
};
```

No `submit`, trocar o bloco `const code = ...` até o `return;` por:
```ts
    const err = await login(email, password);
    setBusy(false);
    if (err) {
      // `forbidden` é a única mensagem da plataforma que vai à tela (spec §3):
      // ela distingue conta desativada / banida / convite pendente.
      setError(
        err.code === "forbidden" && err.message
          ? err.message
          : ERROR_MESSAGES[err.code] ?? ERROR_MESSAGES.unavailable
      );
      return;
    }
```

- [ ] **Step 2: AuthSettings — logout assíncrono**

Em `frontend/src/components/AuthSettings/AuthSettings.tsx`, trocar `signOut`:
```tsx
  async function signOut() {
    await logout();
    navigate("/login");
  }
```
e o docstring `(ADR-0017)` por `(ADR-0017/0018)`.

- [ ] **Step 3: LoginPage.test**

Substituir `frontend/src/features/auth/LoginPage.test.tsx` inteiro por:
```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { stubAuthFetch, TEST_USER } from "../../test/authFetch";
import LoginPage from "./LoginPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLogin(path = "/login") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<div data-testid="app-root">app</div>} />
          <Route path="/c/abc" element={<div data-testid="conversa">conversa</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/e-mail/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/senha/i), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /entrar/i }));
}

const OK = () => new Response(JSON.stringify({ user: TEST_USER, is_admin: false }), { status: 200 });
const isLogin = (url: string) => url.endsWith("/auth/login");

describe("LoginPage", () => {
  it("sucesso navega para o next válido", async () => {
    stubAuthFetch(401, () => OK());
    renderLogin("/login?next=/c/abc");
    fill("ana@x.com", "s3nh4");
    expect(await screen.findByTestId("conversa")).toBeInTheDocument();
  });

  it("next externo é descartado (open redirect)", async () => {
    stubAuthFetch(401, () => OK());
    renderLogin("/login?next=//evil.com/x");
    fill("ana@x.com", "s3nh4");
    expect(await screen.findByTestId("app-root")).toBeInTheDocument();
  });

  it("credencial inválida mostra a mensagem traduzida", async () => {
    stubAuthFetch(401, () =>
      new Response(JSON.stringify({ detail: "invalid-credentials" }), { status: 401 })
    );
    renderLogin();
    fill("a@x.com", "errada");
    expect(await screen.findByText(/e-mail ou senha inválidos/i)).toBeInTheDocument();
  });

  it("forbidden mostra a mensagem da plataforma (única exceção ao erro traduzido)", async () => {
    stubAuthFetch(401, () =>
      new Response(
        JSON.stringify({ detail: "forbidden", message: "Sua conta está desativada." }),
        { status: 403 }
      )
    );
    renderLogin();
    fill("a@x.com", "s");
    expect(await screen.findByText("Sua conta está desativada.")).toBeInTheDocument();
  });

  it("não submete duas vezes enquanto espera", async () => {
    let resolve!: (r: Response) => void;
    const pending = new Promise<Response>((r) => (resolve = r));
    const fetchMock = stubAuthFetch(401, () => pending);
    renderLogin();
    fill("a@x.com", "s");
    fireEvent.click(screen.getByRole("button", { name: /entrando/i }));
    const loginCalls = fetchMock.mock.calls.filter(([input]) => isLogin(String(input)));
    expect(loginCalls).toHaveLength(1);
    resolve(OK());
    await waitFor(() => expect(screen.queryByTestId("app-root")).toBeInTheDocument());
  });
});
```

- [ ] **Step 4: RequireAuth.test**

Substituir `frontend/src/components/RequireAuth/RequireAuth.test.tsx` inteiro por:
```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { loggedIn, stubAuthFetch } from "../../test/authFetch";
import { RequireAuth } from "./RequireAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAt(path = "/") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<div>tela de login</div>} />
          <Route
            path="*"
            element={
              <RequireAuth>
                <div>conteúdo privado</div>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

describe("RequireAuth", () => {
  it("deslogado (/auth/me 401): redireciona para /login", async () => {
    stubAuthFetch(401);
    renderAt("/c/abc");
    expect(await screen.findByText("tela de login")).toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();
  });

  it("logado (/auth/me 200): renderiza o conteúdo", async () => {
    stubAuthFetch(loggedIn());
    renderAt("/");
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });

  it("rede fora no /auth/me: não é 'deslogado' — mostra retry, não o login", async () => {
    const fetchMock = stubAuthFetch("network");
    renderAt("/c/abc");

    expect(await screen.findByText(/não foi possível verificar sua sessão/i)).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: /tentar de novo/i });
    // Erro transitório NÃO derruba para /login nem libera o conteúdo sem sessão.
    expect(screen.queryByText("tela de login")).not.toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();

    // A rede volta e a sessão (cookie) ainda vale: retry reavalia e libera.
    fetchMock.setMe(loggedIn());
    fireEvent.click(retryButton);
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Sidebar.test**

Substituir `frontend/src/features/chat/components/Sidebar.test.tsx` inteiro por:
```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../../hooks/useAuth";
import { loggedIn, stubAuthFetch } from "../../../test/authFetch";
import { Sidebar } from "./Sidebar";

afterEach(() => vi.unstubAllGlobals());

function renderSidebar() {
  const fetchMock = stubAuthFetch(loggedIn());
  render(
    <AuthProvider>
      <MemoryRouter>
        <Sidebar conversations={[]} activeId={null} onNew={vi.fn()} onOpen={vi.fn()} />
      </MemoryRouter>
    </AuthProvider>
  );
  return fetchMock;
}

describe("Sidebar", () => {
  it("rodapé mostra a conta logada e o sair — sem controle de tema", async () => {
    const fetchMock = renderSidebar();
    expect(screen.queryByRole("group", { name: "Tema da interface" })).not.toBeInTheDocument();
    // O rodapé só aparece depois que /auth/me responde (restore é assíncrono).
    expect(await screen.findByText("ana@x.com")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-foot")).toHaveTextContent("ana@x.com");

    fireEvent.click(screen.getByRole("button", { name: /sair/i }));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/logout$/),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("lista vazia ganha um empty state em vez de espaço morto", () => {
    renderSidebar();
    expect(screen.getByText(/conversas aparecem aqui/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: App.test**

Em `frontend/src/App.test.tsx`:

Trocar os imports de sessão:
```tsx
import { loggedIn, stubAuthFetch, type MeOutcome } from "./test/authFetch";
```
(remover `import { clearSession, saveSession } from "./lib/auth/session";`).

Substituir a função `renderAt` por (mesmos stubs de ops/conversas, agora como `fallback`):
```tsx
function renderAt(path: string, me: MeOutcome = loggedIn()) {
  stubMatchMedia(true);
  stubAuthFetch(me, (url) => {
    if (/\/ops\/overview/.test(url)) {
      return new Response(JSON.stringify(OPS_OVERVIEW_STUB), { status: 200 });
    }
    if (/\/ops\/turns/.test(url)) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (/\/ops\/eval/.test(url)) {
      return new Response(JSON.stringify(OPS_EVAL_STUB), { status: 200 });
    }
    if (/\/conversations\/[^/]+$/.test(url)) {
      return new Response(JSON.stringify({ id: "abc-123", title: null, messages: [] }), {
        status: 200,
      });
    }
    return new Response(JSON.stringify([]), { status: 200 });
  });
  return render(
    <AuthProvider>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <App />
        </MemoryRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}
```

Apagar `seedSession()` e `seedAdminSession()` e todas as chamadas `seedSession();` no corpo dos testes (o default de `renderAt` já é logado). No `afterEach`, remover `localStorage.clear();` e `clearSession();` (fica `vi.unstubAllGlobals()` + o `removeAttribute("data-theme")`).

Testes que mudam de chamada:
- `"sem sessão, a raiz cai no /login"`: `renderAt("/", 401);`
- `"admin acessando /ops direto (deep-link) ..."`: `renderAt("/ops", loggedIn(true));`

Atualizar o comentário acima do antigo `seedSession` para: `// Sessão vem de GET /auth/me (ADR-0018) — o stub de fetch decide se o usuário está logado.`

- [ ] **Step 7: rodar a suíte inteira do frontend + build**

```bash
cd frontend && npx vitest run && npm run build
```
Expected: todos os testes PASS; `tsc --noEmit` sem erro (inclusive `architectureMap.test.ts`, que não referencia arquivos de auth). Se `tsc` reclamar de `fetchMock.mock.calls` no LoginPage.test, tipar `([input]: [RequestInfo | URL, ...unknown[]])`.

Verificar que não sobrou nada da v1:
```bash
grep -rn "authHeaders\|lib/auth/session\|accessToken\|localStorage" frontend/src --include=*.ts --include=*.tsx
```
Expected: nenhuma ocorrência (o `lib/theme.ts` pode usar `localStorage` para o tema — isso é legítimo e fica).

- [ ] **Step 8: commit**

```bash
git add frontend/src
git commit -m "feat(frontend/auth): forbidden exibe a mensagem da plataforma; logout assíncrono; testes de App/RequireAuth/Sidebar/Login via /auth/me"
```

---

### Task 8: Verificação final

- [ ] **Step 1: suíte completa do backend**

```bash
uv run pytest -q
```
Expected: PASS. Anotar contagem.

- [ ] **Step 2: lint**

```bash
uv run prospector src main.py
```
Expected: sem mensagens novas nos arquivos tocados (comparar com `git stash`-free baseline: rodar `uv run prospector src/domain/users src/app/api src/support/clients/borderless`).

- [ ] **Step 3: sanidade de boot + migrations**

```bash
uv run python -c "from main import app; print('OK')"
uv run alembic check
uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: `OK`; "No new upgrade operations detected."; downgrade/upgrade sem erro.

- [ ] **Step 4: frontend**

```bash
cd frontend && npx vitest run && npm run build
```
Expected: PASS + build ok.

- [ ] **Step 5: smoke manual em dev (se a plataforma estiver acessível e houver usuário de teste)**

```bash
uv run uvicorn main:app --reload  # terminal 1
cd frontend && npm run dev          # terminal 2
```
No browser: `/login` → credenciais reais → redireciona; DevTools → Application → Cookies mostra `ob_session` HttpOnly; reload mantém logado (`GET /auth/me` 200); "Sair" → `POST /auth/logout` 204 e volta ao `/login`. Sem usuário de teste, registrar como pendência (§8 do spec).

- [ ] **Step 6: memória e relatório**

Atualizar a memória `auth-brainstorm-status.md` (auto-memory do Claude): v2 implementada em 2026-09-04 na branch `feat/autenticacao`; pendências restantes = usuário de teste em staging, política para `emailVerified:false`, confirmação do rate limit por IP; deploy exige SPA e API no mesmo host.

---

## Self-review (feito ao escrever o plano)

**Cobertura do spec §0/§4/§5/§9/§10/§11:**
- Signin sem key → Task 2. Validação por request com cache 60s → Task 3 (`ResolveSessionAction`) + Task 4 (`require_user`). Tabela `sessions` → Task 1. Cookie httpOnly → Task 4. `/auth/me` restore → Task 4 + Task 6. Logout com signout na plataforma → Task 3 + Task 4 + Task 6. Erros por `error.type`, `FORBIDDEN` com message → Task 2 (client), Task 4 (handler testado na integração), Task 6/7 (SPA). Envs mortas + `pyjwt` → Task 5. Rate limit mantido → Task 3. `tests/fakes/auth.py` → fixture de sessão → Task 4. `session.ts`/`authHeaders` removidos → Task 6. RequireAuth 3 estados com rede → Task 6/7. Demo mode → Task 6 (`DEMO_SESSION` sem token). CLAUDE.md → Task 5. `Secure` fora de dev → Task 4 (`_secure()`). Fail-open 10min → Task 3/4.
- §4.3 "GetCurrentUserAction dispensável" → `/auth/me` é projeção pura no controller (Task 4).
- §5 "falha de rede/5xx = error com retry" → Task 6 (`restore`) + Task 7 (`RequireAuth.test`).
- §7 fora de escopo respeitado (sem signup/reset/entitlements/CSRF split-host).

**Tipos consistentes entre tasks:** `UserSession` (Task 1) usado em 3/4; `UserSessionRepository.get_by_token_hash/create/mark_platform_checked/delete` (Task 1) usados em Task 3 e nas fakes; `SignInResult.session_token` (Task 3) lido por `SessionResponse.from_result` e `set_session_cookie` (Task 4); `AuthenticatedUser.name/username` (Task 3) lidos por `SessionResponse.from_authenticated_user` (Task 4); `LoginError` (Task 6) consumido pela `LoginPage` (Task 7); `stubAuthFetch(...).setMe` (Task 6) usado em Task 7.

**Placeholders:** nenhum — todo passo de código traz o código.
