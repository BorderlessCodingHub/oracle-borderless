# Agent Navigation — Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Oracle into the brain of platform navigation: accept the Platform's bearer token, classify navigation intents, call `POST /api/navigation/resolve` on borderless-api through a dedicated `navigate` graph node, stream the resolved destination to the client before the model finishes its sentence, and persist it with the turn.

**Architecture:** Additive changes on the existing LangGraph turn (gate → retrieve → refuse/answer ⇄ tools). A new `navigate` node sits beside `tools`; the post-`answer` edge routes `navigate_platform` tool calls to it. The node is HTTP-only (no DB) so it runs in the `stream()` phase like `web_search` (ADR-0020). Its result enters the state as `navigation`, which the `EventRedactor` projects (like `citations`) so the `updates` chunk carries it to the wire (ADR-0021). Auth gains a bearer path that reuses the `sessions` table and `ResolveSessionAction`'s cache/fail-open. Domain never imports langgraph; `support/` never imports `domain/` (ports stay the boundary).

**Tech Stack:** FastAPI, LangGraph 1.x + langchain-core, httpx, SQLAlchemy 2 async, Alembic, Pydantic v2, pytest + pytest-asyncio, uv. Postgres for integration tests (`tests/integration`).

**Spec:** `docs/superpowers/specs/2026-09-08-agent-navigation-design.md` (sections 3, 5 and 7 bind this repo). The borderless-api side is already implemented on its `feat/agent-navigation` branch: `GET /api/navigation/catalog`, `POST /api/navigation/resolve` (see `borderless-api/docs/navigation-api.md`).

## Global Constraints

- CLAUDE.md non-negotiables: Entities are pure dataclasses; Models are SQLAlchemy; Mappers convert; Actions are the use cases (`*Action.execute()`), no Service facades; controllers thin; Pydantic schemas only in `src/app/api/`; DB session from `CurrentAsyncSessionContext`, never created by hand; `src/domain/` never imports `src/support/agent/graph` or langgraph — it consumes `src/support/agent/ports.py`; `src/support/` never imports `src/domain/`.
- Regra 4 (confidentiality) applies to the wire: only allowlisted, projected fields leave the redactor. `navigation` is projected with an explicit key allowlist. The platform token NEVER enters `metadata`, logs, or events — it lives only in `configurable` and in `sessions.platform_access_token`.
- ADR-0020 phases: anything touching the DB runs in `prelude()`; the `navigate` node is HTTP-only and runs in `stream()`.
- ADR-0021 contract: the wire carries `StreamEvent`s; the client never injects `configurable`. New client inputs go in `input` (`mode`, `locale`).
- borderless-api contract (fixed): `POST {BORDERLESS_AUTH_URL}/api/navigation/resolve` body `{destination, topic?, goal?}` → `{ data: { destination:{id,path,labelKey?,label?}, access, unlock, signals:{matchedTags,inProgress,difficulty,fallback,profile:{membership,seniority,careerStage}}, alternatives[] } }`; unknown destination → `400` with `error.type = "VALIDATION"` and `error.details.validDestinations: string[]`; `GET /api/navigation/catalog` → `{ data: { destinations: [{id,kind,path,labelKey,description,fallbackId?}] } }`. Both require `Authorization: Bearer <platform token>`.
- One navigation per turn. Never invent destinations. Answer in the `locale` given.
- Migrations: linear Alembic chain, file `database/migrations/versions/00NN_<slug>.py`, `revision`/`down_revision` strings, reversible `downgrade()`.
- Tests: `uv run pytest tests/unit` must stay green without a DB; `tests/integration` uses the local Postgres (`docker/docker-compose.yml`). Every task ends with the covering unit tests green and `uv run prospector` (or the repo's lint) clean on touched files.
- Commit messages: conventional commits in Portuguese, matching the repo history (`feat(turno): …`, `fix(api): …`, `docs(adr): …`). Never commit `.env`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `database/migrations/versions/0010_sessions_bearer_profile.py` | `sessions.source` + profile snapshot columns. |
| `src/domain/users/entities/user_session.py`, `models/user_session.py`, `mappers/user_session_mapper.py`, `repositories/user_session_repository.py` | Session gains `source`, `user_membership`, `user_seniority`, `user_career_stage`; repo gains `update_profile_snapshot`. |
| `src/domain/users/entities/authenticated_user.py` | Gains `platform_access_token`, `membership`, `seniority`, `career_stage`. |
| `src/support/clients/borderless/borderless_auth_client.py` | `PlatformProfile` gains `seniority`, `career_stage`. |
| `src/domain/users/actions/resolve_session_action.py` | Refreshes the snapshot on revalidation; returns the richer `AuthenticatedUser`. |
| `src/domain/users/actions/resolve_bearer_action.py` | Bearer → find-or-create session → `AuthenticatedUser`. |
| `src/app/api/dependencies/require_user.py` | Reads `Authorization: Bearer` before the cookie. |
| `src/app/api/requests/stream_events_request.py` | `input.mode`, `input.locale`. |
| `src/domain/conversations/dtos/opened_turn.py`, `actions/open_turn_action.py`, `actions/run_turn_action.py` | Carry `mode`/`locale`/`extra_config` to the graph. |
| `src/support/agent/ports.py` | `TurnGraphPort.run(mode, locale)`, `navigation_of()`, `TurnSignals` navigation fields, `NavigationResolverPort`. |
| `src/support/agent/graph/state.py`, `edges.py`, `nodes.py`, `builder.py`, `runner.py` | `mode/locale/intent/navigation` in state; gate intent; `after_answer` edge; `navigate` node; redactor projection. |
| `src/support/agent/graph/navigate_node.py` | The node: executes `navigate_platform` via the resolver port; one per turn. |
| `src/support/clients/borderless/borderless_navigation_client.py` | httpx client for resolve/catalog; error mapping. |
| `src/support/agent/navigation_catalog.py` + `navigation_catalog_snapshot.json` | Catalog cache (1h, per process) with bundled fallback; builds the tool description. |
| `src/support/agent/tools.py`, `prompts.py` | `navigate_platform` declaration; NAVEGAÇÃO prompt block; profile/locale in the answer prompt. |
| `database/migrations/versions/0011_navigation_persistence.py` | `messages.navigation` JSONB; `agent_traces.intent/navigation_called/navigation_access`. |
| `src/domain/conversations/entities/message.py`, `models/message.py`, `mappers/message_mapper.py`, `actions/append_assistant_message_action.py` | Persist `navigation`. |
| `src/domain/observability/dtos/turn_trace_draft.py`, `entities/turn_trace.py`, `models/turn_trace.py`, `mappers/turn_trace_mapper.py` | Trace columns. |
| `src/app/api/controllers/conversation_controller.py`, `responses/conversation_responses.py` | Wire mode/locale/extra_config; capture navigation; expose it on GET. |
| `evals/models.py`, `evals/runner.py`, `evals/cases/navigation_set.json`, `evals/__main__.py` | `navigation` category with deterministic `navigation_target` metric via a fake resolver. |
| `docs/adr/ADR-0022-navigation-tool.md`, `CLAUDE.md`, `.env.example`, `docs/architecture.md` | Documentation. |
| Tests under `tests/unit/**` mirroring each file; `tests/fakes/fake_navigation_client.py`; `tests/fakes/fake_turn_graph.py` updated. |

---

### Task 1: Session snapshot + bearer resolution (domain)

**Files:**
- Create: `database/migrations/versions/0010_sessions_bearer_profile.py`
- Modify: `src/domain/users/models/user_session.py`, `src/domain/users/entities/user_session.py`, `src/domain/users/mappers/user_session_mapper.py`, `src/domain/users/repositories/user_session_repository.py`
- Modify: `src/domain/users/entities/authenticated_user.py`
- Modify: `src/support/clients/borderless/borderless_auth_client.py` (`PlatformProfile`, `get_profile`)
- Modify: `src/domain/users/actions/resolve_session_action.py`, `src/domain/users/actions/sign_in_action.py`
- Create: `src/domain/users/actions/resolve_bearer_action.py`
- Test: `tests/unit/domain/users/test_resolve_bearer_action.py`, extend `tests/unit/domain/users/test_resolve_session_action.py`, `tests/unit/support/test_borderless_auth_client.py`, `tests/integration/domain/users/test_user_session_repository.py`

**Interfaces:**
- Produces: `UserSession(source: str = "oracle_login", user_membership: str | None = None, user_seniority: str | None = None, user_career_stage: str | None = None)`; `UserSessionRepository.update_profile_snapshot(session_id, checked_at, membership, seniority, career_stage)`; `PlatformProfile(seniority: str | None, career_stage: str | None)`; `AuthenticatedUser(platform_access_token: str | None = None, membership: str | None = None, seniority: str | None = None, career_stage: str | None = None)`; `ResolveBearerAction(auth_client, sessions=None, clock=None).execute(raw_bearer) -> AuthenticatedUser | None`.

- [ ] **Step 1: Failing tests for the bearer action**

```python
# tests/unit/domain/users/test_resolve_bearer_action.py
"""ResolveBearerAction: header Authorization → sessão por hash do token da
plataforma → find-or-create validando em /api/users/profile. Reusa o cache/
fail-open de ResolveSessionAction quando a sessão já existe."""

from datetime import datetime, timedelta, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.actions.resolve_bearer_action import ResolveBearerAction
from src.domain.users.actions.resolve_session_action import PLATFORM_CHECK_TTL_S
from src.domain.users.entities.user_session import UserSession
from src.support.clients.borderless.borderless_auth_client import PlatformProfile
from src.support.core.exceptions import ExternalServiceUnavailableError
from src.support.utils.session_tokens import hash_session_token

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
BEARER = "opaque-platform-token"
PROFILE = PlatformProfile(
    id="u-1", email="ana@x.com", name="Ana", username="ana", membership="STARTER",
    community_role="MEMBER", seniority="JUNIOR", career_stage="junior_transition",
)


class FakeSessions:
    def __init__(self, row: UserSession | None = None):
        self.row = row
        self.created: list[UserSession] = []
        self.snapshots: list[tuple] = []
        self.deleted: list = []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def create(self, session):
        self.created.append(session)
        self.row = session
        return session

    async def mark_platform_checked(self, session_id, checked_at):
        pass

    async def update_profile_snapshot(self, session_id, checked_at, membership, seniority, career_stage):
        self.snapshots.append((session_id, membership, seniority, career_stage))

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[str] = []

    async def get_profile(self, access_token):
        self.calls.append(access_token)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _existing(checked_seconds_ago=0) -> UserSession:
    checked = NOW - timedelta(seconds=checked_seconds_ago)
    return UserSession(
        uuid=uuid7(), token_hash=hash_session_token(BEARER), platform_access_token=BEARER,
        user_id="u-1", user_email="ana@x.com", user_name="Ana", user_username="ana",
        last_platform_check_at=checked, created_at=checked, updated_at=checked,
        source="platform_bearer", user_membership="FREE", user_seniority=None, user_career_stage="curious",
    )


def _action(sessions, client):
    return ResolveBearerAction(auth_client=client, sessions=sessions, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_bearer_desconhecido_valido_cria_sessao_com_snapshot_do_perfil():
    sessions, client = FakeSessions(None), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == [BEARER]
    assert len(sessions.created) == 1
    created = sessions.created[0]
    assert created.token_hash == hash_session_token(BEARER)
    assert created.platform_access_token == BEARER
    assert created.source == "platform_bearer"
    assert (created.user_membership, created.user_seniority, created.user_career_stage) == ("STARTER", "JUNIOR", "junior_transition")
    assert created.last_platform_check_at == NOW
    assert user is not None
    assert (user.id, user.email, user.platform_access_token) == ("u-1", "ana@x.com", BEARER)
    assert (user.membership, user.seniority, user.career_stage) == ("STARTER", "JUNIOR", "junior_transition")


@pytest.mark.asyncio
async def test_bearer_desconhecido_invalido_devolve_none_sem_criar_sessao():
    sessions, client = FakeSessions(None), FakeClient(None)
    assert await _action(sessions, client).execute(BEARER) is None
    assert sessions.created == []


@pytest.mark.asyncio
async def test_bearer_desconhecido_com_plataforma_fora_propaga_503():
    sessions, client = FakeSessions(None), FakeClient(ExternalServiceUnavailableError("fora"))
    with pytest.raises(ExternalServiceUnavailableError):
        await _action(sessions, client).execute(BEARER)
    assert sessions.created == []


@pytest.mark.asyncio
async def test_bearer_conhecido_dentro_do_cache_nao_vai_a_plataforma_e_le_o_snapshot():
    sessions, client = FakeSessions(_existing(PLATFORM_CHECK_TTL_S - 1)), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == []
    assert user is not None
    assert user.platform_access_token == BEARER
    assert (user.membership, user.seniority, user.career_stage) == ("FREE", None, "curious")


@pytest.mark.asyncio
async def test_bearer_conhecido_fora_do_cache_revalida_e_atualiza_o_snapshot():
    row = _existing(PLATFORM_CHECK_TTL_S + 1)
    sessions, client = FakeSessions(row), FakeClient(PROFILE)
    user = await _action(sessions, client).execute(BEARER)
    assert client.calls == [BEARER]
    assert sessions.snapshots == [(row.uuid, "STARTER", "JUNIOR", "junior_transition")]
    assert (user.membership, user.seniority, user.career_stage) == ("STARTER", "JUNIOR", "junior_transition")


@pytest.mark.asyncio
async def test_bearer_conhecido_revogado_na_plataforma_apaga_a_sessao_e_devolve_none():
    row = _existing(PLATFORM_CHECK_TTL_S + 1)
    sessions, client = FakeSessions(row), FakeClient(None)
    assert await _action(sessions, client).execute(BEARER) is None
    assert sessions.deleted == [row.uuid]


@pytest.mark.asyncio
async def test_bearer_vazio_devolve_none_sem_consultar_nada():
    sessions, client = FakeSessions(None), FakeClient(PROFILE)
    assert await _action(sessions, client).execute("   ") is None
    assert client.calls == []
```

Also add to `tests/unit/support/test_borderless_auth_client.py`: a profile body containing `"seniority": "JUNIOR", "careerStage": "junior_transition"` parses into `PlatformProfile.seniority == "JUNIOR"` and `.career_stage == "junior_transition"`; a body without them yields `None` for both.

Add to `tests/integration/domain/users/test_user_session_repository.py`: `create` persists `source`/snapshot columns and `update_profile_snapshot` updates them plus `last_platform_check_at`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/domain/users/test_resolve_bearer_action.py -q`
Expected: FAIL — `ModuleNotFoundError: resolve_bearer_action`.

- [ ] **Step 3: Migration 0010**

```python
# database/migrations/versions/0010_sessions_bearer_profile.py
"""sessions — origem da sessão (cookie do oráculo ou bearer da plataforma) e
snapshot do perfil (membership, seniority, careerStage) usado no prompt de
navegação sem ir à rede a cada turno.

Revision ID: 0010_sessions_bearer_profile
Revises: 0009_sessions
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_sessions_bearer_profile"
down_revision = "0009_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("source", sa.String(32), nullable=False, server_default="oracle_login"))
    op.add_column("sessions", sa.Column("user_membership", sa.String(16), nullable=True))
    op.add_column("sessions", sa.Column("user_seniority", sa.String(16), nullable=True))
    op.add_column("sessions", sa.Column("user_career_stage", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "user_career_stage")
    op.drop_column("sessions", "user_seniority")
    op.drop_column("sessions", "user_membership")
    op.drop_column("sessions", "source")
```

- [ ] **Step 4: Model, entity, mapper, repository**

`UserSessionModel` adds:

```python
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="oracle_login")
    user_membership: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_seniority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_career_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

`UserSession` entity adds (after `updated_at`, with defaults so existing constructors keep working):

```python
    source: str = "oracle_login"  # "oracle_login" | "platform_bearer"
    user_membership: str | None = None
    user_seniority: str | None = None
    user_career_stage: str | None = None
```

`UserSessionMapper.to_entity/to_model_attrs` copy the four fields. `UserSessionRepository` adds:

```python
    async def update_profile_snapshot(
        self, session_id: UUID, checked_at: datetime,
        membership: str | None, seniority: str | None, career_stage: str | None,
    ) -> None:
        await self.session.execute(
            update(UserSessionModel)
            .where(UserSessionModel.uuid == session_id)
            .values(
                last_platform_check_at=checked_at,
                user_membership=membership,
                user_seniority=seniority,
                user_career_stage=career_stage,
            )
        )
```

`AuthenticatedUser` adds:

```python
    platform_access_token: str | None = None  # só no servidor; nunca em eventos/logs
    membership: str | None = None
    seniority: str | None = None
    career_stage: str | None = None
```

`PlatformProfile` adds `seniority: str | None` and `career_stage: str | None`; `get_profile` fills them with `user.get("seniority")` and `user.get("careerStage")`.

- [ ] **Step 5: ResolveSessionAction refresh + ResolveBearerAction**

In `ResolveSessionAction.execute`, when `profile` is obtained (cache miss path), replace `mark_platform_checked(...)` with `update_profile_snapshot(session.uuid, now, profile.membership, profile.seniority, profile.career_stage)` and keep the in-memory values for the returned user. Return:

```python
        return AuthenticatedUser(
            id=session.user_id,
            email=session.user_email,
            is_admin=session.user_email in settings.admin_emails,
            name=session.user_name,
            username=session.user_username,
            platform_access_token=session.platform_access_token,
            membership=membership,
            seniority=seniority,
            career_stage=career_stage,
        )
```

where `membership/seniority/career_stage` default to the session snapshot and are overwritten by the fresh profile when one was fetched. Keep `mark_platform_checked` in the repository for `tests/fakes` compatibility.

`SignInAction` passes `source="oracle_login"` and the snapshot from `data.user.career_stage` (membership/seniority are not in the signin payload → `None`; the first cache-miss revalidation fills them).

```python
# src/domain/users/actions/resolve_bearer_action.py
"""Bearer da plataforma → sessão do oráculo (find-or-create) → identidade.

Caminho do proxy do Next.js (spec §3/§5.1): o cliente já está logado na
Platform e manda `Authorization: Bearer <token opaco>`. A sessão é chaveada
pelo hash desse token, com `source = "platform_bearer"`, e a partir daí segue
o cache/fail-open de ResolveSessionAction. Um bearer nunca visto é validado
UMA vez em /api/users/profile antes de virar sessão."""

from datetime import datetime, timezone
from typing import Callable

from uuid6 import uuid7

from src.domain.users.actions.resolve_session_action import ResolveSessionAction
from src.domain.users.entities.authenticated_user import AuthenticatedUser
from src.domain.users.entities.user_session import UserSession
from src.domain.users.repositories.user_session_repository import UserSessionRepository
from src.support.clients.borderless.borderless_auth_client import BorderlessAuthClient
from src.support.core.settings import settings
from src.support.utils.session_tokens import hash_session_token

SOURCE_PLATFORM_BEARER = "platform_bearer"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResolveBearerAction:
    def __init__(
        self,
        auth_client: BorderlessAuthClient,
        sessions: UserSessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.auth_client = auth_client
        self.sessions = sessions if sessions is not None else UserSessionRepository()
        self.clock = clock or _utcnow

    async def execute(self, raw_bearer: str) -> AuthenticatedUser | None:
        raw_bearer = (raw_bearer or "").strip()
        if not raw_bearer:
            return None

        existing = await self.sessions.get_by_token_hash(hash_session_token(raw_bearer))
        if existing is not None:
            return await ResolveSessionAction(
                auth_client=self.auth_client, sessions=self.sessions, clock=self.clock
            ).execute(raw_bearer)

        profile = await self.auth_client.get_profile(raw_bearer)
        if profile is None:
            return None

        now = self.clock()
        await self.sessions.create(
            UserSession(
                uuid=uuid7(),
                token_hash=hash_session_token(raw_bearer),
                platform_access_token=raw_bearer,
                user_id=profile.id,
                user_email=profile.email,
                user_name=profile.name,
                user_username=profile.username,
                last_platform_check_at=now,
                created_at=now,
                updated_at=now,
                source=SOURCE_PLATFORM_BEARER,
                user_membership=profile.membership,
                user_seniority=profile.seniority,
                user_career_stage=profile.career_stage,
            )
        )
        return AuthenticatedUser(
            id=profile.id,
            email=profile.email,
            is_admin=profile.email in settings.admin_emails,
            name=profile.name,
            username=profile.username,
            platform_access_token=raw_bearer,
            membership=profile.membership,
            seniority=profile.seniority,
            career_stage=profile.career_stage,
        )
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/unit/domain/users tests/unit/support/test_borderless_auth_client.py -q` → PASS. Then `docker compose -f docker/docker-compose.yml up -d && uv run alembic upgrade head && uv run pytest tests/integration/domain/users -q` → PASS (skip integration with a note if Postgres is unavailable).

- [ ] **Step 7: Commit**

```bash
git add database/migrations/versions/0010_sessions_bearer_profile.py src/domain/users src/support/clients/borderless/borderless_auth_client.py tests/unit/domain/users tests/unit/support/test_borderless_auth_client.py tests/integration/domain/users
git commit -m "feat(auth): sessão por bearer da plataforma com snapshot de perfil (source, membership, seniority, careerStage)"
```

---

### Task 2: `require_user` accepts `Authorization: Bearer`

**Files:**
- Modify: `src/app/api/dependencies/require_user.py`
- Test: `tests/unit/app/api/test_require_user.py`

**Interfaces:**
- Consumes: `ResolveBearerAction` (Task 1).
- Produces: bearer path in `require_user`; cookie path unchanged.

- [ ] **Step 1: Failing tests** — add to `tests/unit/app/api/test_require_user.py` a `FakeResolveBearer` (same shape as `FakeResolve`, patched onto `mod.ResolveBearerAction`) and:

```python
def _request_with_auth(header: str, cookie: str | None = None) -> Request:
    headers = [(b"authorization", header.encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_bearer_valido_devolve_user_sem_olhar_o_cookie():
    from src.app.api.dependencies.require_user import require_user
    FakeResolveBearer.outcome = ANA
    user = await require_user(_request_with_auth("Bearer plat-123", f"{SESSION_COOKIE_NAME}=cookie-x"))
    assert user is ANA
    assert FakeResolveBearer.seen == ["plat-123"]
    assert FakeResolve.seen == []
    assert CurrentRequestContext.get_user() is ANA


@pytest.mark.asyncio
async def test_bearer_invalido_da_401_sem_apagar_cookie():
    from src.app.api.dependencies.require_user import require_user
    FakeResolveBearer.outcome = None
    with pytest.raises(HTTPException) as exc:
        await require_user(_request_with_auth("Bearer nope"))
    assert exc.value.status_code == 401
    assert exc.value.headers is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer   ", "bearer x y"])
async def test_authorization_malformado_cai_no_caminho_do_cookie(header):
    from src.app.api.dependencies.require_user import require_user
    FakeResolve.outcome = ANA
    user = await require_user(_request_with_auth(header, f"{SESSION_COOKIE_NAME}=tok-1"))
    assert user is ANA
    assert FakeResolveBearer.seen == []
```

- [ ] **Step 2: Run** → FAIL (no `ResolveBearerAction` in module).

- [ ] **Step 3: Implement**

```python
def read_bearer_token(request: Request) -> str | None:
    """`Authorization: Bearer <token>` — exatamente dois campos; qualquer outra
    forma é ignorada e a autenticação segue pelo cookie."""
    raw = request.headers.get("authorization") or ""
    parts = raw.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


async def require_user(request: Request) -> AuthenticatedUser:
    bearer = read_bearer_token(request)
    if bearer is not None:
        user = await ResolveBearerAction(auth_client=BorderlessAuthClient()).execute(bearer)
        if user is None:
            raise HTTPException(status_code=401, detail="not-authenticated")
        CurrentRequestContext.set_user(user)
        return user
    # ... caminho do cookie inalterado ...
```

Update the module docstring to mention the bearer path (spec §5.1).

- [ ] **Step 4: Run** `uv run pytest tests/unit/app/api/test_require_user.py -q` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(auth): require_user aceita Authorization: Bearer da plataforma"`

---

### Task 3: `mode` and `locale` travel from the request into the graph state

**Files:**
- Modify: `src/app/api/requests/stream_events_request.py`
- Modify: `src/support/agent/ports.py` (`TurnGraphPort.run`), `src/support/agent/graph/runner.py` (`_initial_state`, `run`), `src/support/agent/graph/state.py`
- Modify: `src/domain/conversations/dtos/opened_turn.py`, `actions/open_turn_action.py`, `actions/run_turn_action.py`
- Modify: `tests/fakes/fake_turn_graph.py` (accept `mode`, `locale`), `tests/fakes/stream_events.py` (`ask_body(mode=, locale=)`)
- Test: `tests/unit/app/api/requests/test_stream_events_request.py`, `tests/unit/support/agent/graph/test_runner.py`, `tests/unit/domain/conversations/actions/test_open_turn_action.py` (if present; else create a minimal one)

**Interfaces:**
- Produces: `StreamInput.mode: Literal["chat","navigate"] = "chat"`, `StreamInput.locale: Literal["en","pt-BR"] = "pt-BR"`, `StreamEventsRequest.mode/.locale`; `OpenedTurn.mode/.locale`; `OpenTurnAction.execute(question, conversation_id, user_email, mode="chat", locale="pt-BR")`; `RunTurnAction.execute(turn, extra_config=None)`; `TurnGraphPort.run(..., mode="chat", locale="pt-BR", extra_config=None)`; state keys `mode`, `locale`, `intent` (`"navigate"` preset when `mode == "navigate"`, `retrieve=False`), `navigation: dict | None`.

- [ ] **Step 1: Failing tests**

`test_stream_events_request.py`:

```python
def test_mode_and_locale_default_to_chat_and_pt_br():
    req = StreamEventsRequest.model_validate(_body())
    assert (req.mode, req.locale) == ("chat", "pt-BR")


def test_mode_navigate_and_locale_en_are_accepted():
    body = _body()
    body["input"].update({"mode": "navigate", "locale": "en"})
    req = StreamEventsRequest.model_validate(body)
    assert (req.mode, req.locale) == ("navigate", "en")


@pytest.mark.parametrize("field,value", [("mode", "fly"), ("locale", "es")])
def test_unknown_mode_or_locale_is_rejected(field, value):
    body = _body()
    body["input"][field] = value
    with pytest.raises(ValidationError):
        StreamEventsRequest.model_validate(body)
```

`test_runner.py`: `_initial_state("q", [], None, mode="navigate", locale="en")` returns `mode == "navigate"`, `locale == "en"`, `intent == "navigate"`, `retrieve is False`, `navigation is None`; with the default mode `intent` is absent.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

`StreamInput`: add `mode: Literal["chat", "navigate"] = "chat"` and `locale: Literal["en", "pt-BR"] = "pt-BR"`; `StreamEventsRequest` gets `mode`/`locale` properties. Update the module docstring: five fields are ours now.

`TurnState` adds `mode: str`, `locale: str`, `intent: str`, `navigation: dict | None`.

`runner._initial_state(question, history, knowledge, mode="chat", locale="pt-BR")`:

```python
    state = {
        "question": question, "history": history,
        "knowledge": list(knowledge) if knowledge is not None else [],
        "preset_knowledge": knowledge is not None, "messages": [],
        "mode": mode, "locale": locale, "navigation": None,
    }
    if mode == "navigate":
        # A barra fixa a intenção: sem gate, sem RAG, sem recusa (spec §5.3).
        state.update({"intent": "navigate", "retrieve": False, "search_query": "", "degraded": False})
    return state
```

`TurnGraphRunner.run(..., mode="chat", locale="pt-BR", extra_config=None)` forwards them; `TurnGraphPort.run` signature updated in `ports.py`.

`OpenedTurn` adds `mode: str = "chat"`, `locale: str = "pt-BR"`. `OpenTurnAction.execute(..., mode="chat", locale="pt-BR")` stores them. `RunTurnAction.execute(turn, extra_config=None)` calls `self.graph.run(turn.question, turn.history, deps, turn.signals, mode=turn.mode, locale=turn.locale, extra_config=extra_config)`.

`FakeTurnGraph.run(...)` accepts `mode="chat", locale="pt-BR"` kwargs and records them (`self.received_mode`, `self.received_locale`). `ask_body(question, thread_id=None, run_id=None, mode=None, locale=None)` adds the keys to `input` only when given.

- [ ] **Step 4: Run** `uv run pytest tests/unit -q` → PASS (all existing callers still work thanks to defaults).

- [ ] **Step 5: Commit** `git commit -m "feat(turno): mode e locale entram pelo input e atravessam o state do grafo"`

---

### Task 4: Gate learns `intent`; edges route navigation away from retrieval

**Files:**
- Modify: `src/support/agent/graph/nodes.py` (`GATE_SYSTEM_PROMPT`, `_GateOutput`, `gate_node`), `src/support/agent/graph/edges.py`, `src/support/agent/ports.py` (`TurnSignals.intent`)
- Test: `tests/unit/support/agent/graph/test_nodes.py`, `tests/unit/support/agent/graph/test_edges.py`

**Interfaces:**
- Produces: `_GateOutput.intent: Literal["knowledge","navigate","chit_chat"] = "knowledge"`; `gate_node` returns `intent`; fail-open → `intent="knowledge"`; `route_entry` returns `"answer"` when `state.get("mode") == "navigate"`; `should_retrieve` returns `"retrieve"` only when `retrieve` and `intent in (None, "knowledge")`; `TurnSignals.intent: str | None = None`.

- [ ] **Step 1: Failing tests**

`test_edges.py`:

```python
def test_navigate_mode_skips_the_gate():
    assert route_entry({"mode": "navigate", "intent": "navigate"}) == "answer"


def test_a_navigation_intent_never_retrieves_even_if_the_gate_said_so():
    assert should_retrieve({"retrieve": True, "intent": "navigate"}) == "answer"


def test_chit_chat_never_retrieves():
    assert should_retrieve({"retrieve": True, "intent": "chit_chat"}) == "answer"


def test_a_knowledge_intent_keeps_retrieving():
    assert should_retrieve({"retrieve": True, "intent": "knowledge"}) == "retrieve"
    assert should_retrieve({"retrieve": True}) == "retrieve"  # compat: sem intent = knowledge
```

`test_nodes.py`: gate output with `intent="navigate", retrieve=False` → node returns `intent == "navigate"`, `retrieve is False`, `signals.intent == "navigate"`; a model that returns `intent="navigate", retrieve=True` is normalized to `retrieve False`; the failing gate returns `intent == "knowledge"` and `degraded True`.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

`_GateOutput` gains `intent: Literal["knowledge", "navigate", "chit_chat"] = Field(default="knowledge", description="knowledge=pergunta sobre a base; navigate=quer ir a um lugar/começar algo na plataforma; chit_chat=saudação/conversa")`.

`GATE_SYSTEM_PROMPT` gains, before the `retrieve` rules:

```
Classifique também `intent`:
- navigate: o usuário quer IR a algum lugar da plataforma, ENCONTRAR um conteúdo
  ou COMEÇAR uma atividade (ex.: "quero praticar algoritmos", "me leva para as
  trilhas de backend", "onde vejo meus eventos?", "quero treinar system design").
  Para navigate, retrieve=false e search_query="".
- chit_chat: saudações, agradecimentos, conversa fiada, perguntas sobre você.
- knowledge: qualquer pergunta substantiva sobre o ecossistema, suas regras ou dados.
```

`gate_node`: `retrieve = out.retrieve and out.intent == "knowledge"`; result includes `"intent": out.intent`; fail-open result includes `"intent": "knowledge"`; `signals.intent = result["intent"]`.

`edges.py`:

```python
def route_entry(state: TurnState) -> Literal["answer", "gate"]:
    if state.get("preset_knowledge") or state.get("mode") == "navigate":
        return "answer"
    return "gate"


def should_retrieve(state: TurnState) -> Literal["retrieve", "answer"]:
    intent = state.get("intent", "knowledge")
    return "retrieve" if state.get("retrieve") and intent == "knowledge" else "answer"
```

`TurnSignals.intent: str | None = None`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/support/agent -q` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(turno): gate classifica intent; navegação e conversa nunca passam pelo RAG"`

---

### Task 5: borderless-api navigation client + catalog cache

**Files:**
- Create: `src/support/clients/borderless/borderless_navigation_client.py`
- Create: `src/support/agent/navigation_catalog.py`, `src/support/agent/navigation_catalog_snapshot.json`
- Modify: `src/support/core/settings.py` (`NAVIGATION_CATALOG_TTL_S: int = 3600`, `NAVIGATION_TIMEOUT_SECONDS: float = 8.0`), `.env.example` (commented entries)
- Create: `tests/fakes/fake_navigation_client.py`
- Test: `tests/unit/support/clients/test_borderless_navigation_client.py`, `tests/unit/support/agent/test_navigation_catalog.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) NavigationResult(destination: dict, access: str, unlock: dict | None, signals: dict, alternatives: list[dict])` with `.to_public() -> dict` (allowlisted keys: `destination{id,path,labelKey,label}`, `access`, `unlock`, `signals{matchedTags,inProgress,difficulty,fallback}`, `alternatives[{id,path,labelKey,label}]`) and `.to_tool_text() -> str` (compact JSON for the model, including `signals.profile`).
  - `NavigationValidationError(DomainError)` with `.valid_destinations: list[str]`; `NavigationUnauthorizedError(DomainError)`; network/5xx → `ExternalServiceUnavailableError`.
  - `BorderlessNavigationClient(transport=None).resolve(access_token, destination, topic=None, goal=None) -> NavigationResult` and `.catalog(access_token) -> list[dict]`.
  - `NavigationCatalog.describe(access_token: str | None) -> str` (tool docstring text: one line per destination `- <id> (<kind>): <description>`); `NavigationCatalog.ids(access_token) -> list[str]`; per-process cache `{fetched_at, entries}` with TTL `settings.NAVIGATION_CATALOG_TTL_S`; on any error falls back to the bundled snapshot and logs a warning; `NavigationCatalog.reset()` for tests.
  - `tests/fakes/fake_navigation_client.py`: `FakeNavigationClient(results: dict[str, NavigationResult | Exception], catalog: list[dict] | None = None)` recording `.calls: list[dict]`.

- [ ] **Step 1: Failing tests** (httpx.MockTransport, same pattern as `test_borderless_auth_client.py`)

```python
# tests/unit/support/clients/test_borderless_navigation_client.py
import json
import httpx
import pytest

from src.support.clients.borderless.borderless_navigation_client import (
    BorderlessNavigationClient, NavigationUnauthorizedError, NavigationValidationError,
)
from src.support.core.exceptions import ExternalServiceUnavailableError

RESOLVED = {"data": {
    "destination": {"id": "trail", "path": "/trails/t1", "label": "Backend Node.js"},
    "access": "locked_upgrade",
    "unlock": {"action": "upgrade", "membership": "STARTER", "path": "/settings/purchases"},
    "signals": {"matchedTags": ["nodejs"], "inProgress": False, "difficulty": "BEGINNER", "fallback": False,
                "profile": {"membership": "FREE", "seniority": "JUNIOR", "careerStage": "junior_transition"}},
    "alternatives": [{"id": "trails", "path": "/trails", "labelKey": "navigation.destinations.trails"}],
}}


def _client(handler):
    return BorderlessNavigationClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_resolve_envia_bearer_e_body_e_parseia_o_resultado():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESOLVED)

    result = await _client(handler).resolve("tok", "trail", topic="backend node", goal="learn")
    assert seen == {"auth": "Bearer tok", "path": "/api/navigation/resolve",
                    "body": {"destination": "trail", "topic": "backend node", "goal": "learn"}}
    assert result.destination["path"] == "/trails/t1"
    assert result.access == "locked_upgrade"
    public = result.to_public()
    assert set(public) == {"destination", "access", "unlock", "signals", "alternatives"}
    assert "profile" not in public["signals"]
    assert "profile" in json.loads(result.to_tool_text())["signals"]


@pytest.mark.asyncio
async def test_resolve_omite_topic_e_goal_quando_none():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESOLVED)

    await _client(handler).resolve("tok", "home")
    assert seen["body"] == {"destination": "home"}


@pytest.mark.asyncio
async def test_400_validation_vira_erro_com_ids_validos():
    def handler(request):
        return httpx.Response(400, json={"error": {"type": "VALIDATION", "message": "Unknown navigation destination",
                                                   "details": {"validDestinations": ["home", "trails"]}}})
    with pytest.raises(NavigationValidationError) as exc:
        await _client(handler).resolve("tok", "moon")
    assert exc.value.valid_destinations == ["home", "trails"]


@pytest.mark.asyncio
async def test_401_vira_unauthorized():
    with pytest.raises(NavigationUnauthorizedError):
        await _client(lambda r: httpx.Response(401, json={"error": {"type": "UNAUTHORIZED"}})).resolve("tok", "home")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "500", "malformed"])
async def test_rede_5xx_ou_contrato_quebrado_viram_service_unavailable(failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        if failure == "500":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"data": {"nope": 1}})

    with pytest.raises(ExternalServiceUnavailableError):
        await _client(handler).resolve("tok", "home")


@pytest.mark.asyncio
async def test_catalog_parseia_destinations():
    body = {"data": {"destinations": [{"id": "home", "kind": "static", "path": "/", "labelKey": "navigation.destinations.home", "description": "Dashboard"}]}}
    entries = await _client(lambda r: httpx.Response(200, json=body)).catalog("tok")
    assert entries[0]["id"] == "home"
```

```python
# tests/unit/support/agent/test_navigation_catalog.py
import pytest

from src.support.agent.navigation_catalog import NavigationCatalog
from src.support.core.exceptions import ExternalServiceUnavailableError
from tests.fakes.fake_navigation_client import FakeNavigationClient

ENTRY = {"id": "code_breakers", "kind": "static", "path": "/code-breakers",
         "labelKey": "navigation.destinations.code_breakers", "description": "Algorithm challenges"}


@pytest.fixture(autouse=True)
def _reset():
    NavigationCatalog.reset()
    yield
    NavigationCatalog.reset()


@pytest.mark.asyncio
async def test_busca_uma_vez_e_cacheia():
    client = FakeNavigationClient(results={}, catalog=[ENTRY])
    catalog = NavigationCatalog(client=client, clock=lambda: 1000.0)
    text1 = await catalog.describe("tok")
    text2 = await catalog.describe("tok")
    assert "code_breakers (static): Algorithm challenges" in text1 and text1 == text2
    assert len([c for c in client.calls if c["op"] == "catalog"]) == 1


@pytest.mark.asyncio
async def test_expira_apos_o_ttl(monkeypatch):
    from src.support.core.settings import settings
    monkeypatch.setattr(settings, "NAVIGATION_CATALOG_TTL_S", 10)
    now = {"t": 1000.0}
    client = FakeNavigationClient(results={}, catalog=[ENTRY])
    catalog = NavigationCatalog(client=client, clock=lambda: now["t"])
    await catalog.describe("tok")
    now["t"] += 11
    await catalog.describe("tok")
    assert len([c for c in client.calls if c["op"] == "catalog"]) == 2


@pytest.mark.asyncio
async def test_falha_na_api_usa_o_snapshot_embutido():
    client = FakeNavigationClient(results={}, catalog=ExternalServiceUnavailableError("fora"))
    text = await catalog_text_without_network(client)
    assert "trail (dynamic)" in text and "home (static)" in text


async def catalog_text_without_network(client):
    return await NavigationCatalog(client=client, clock=lambda: 0.0).describe("tok")


@pytest.mark.asyncio
async def test_sem_token_usa_o_snapshot_sem_chamar_a_api():
    client = FakeNavigationClient(results={}, catalog=[ENTRY])
    ids = await NavigationCatalog(client=client, clock=lambda: 0.0).ids(None)
    assert "trail" in ids and client.calls == []


def test_snapshot_tem_os_17_destinos():
    ids = NavigationCatalog.snapshot_ids()
    assert len(ids) == 17 and {"home", "trails", "trail", "program", "event", "livestream"} <= set(ids)
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement the client**

```python
# src/support/clients/borderless/borderless_navigation_client.py
"""Cliente da API de navegação da borderless-api (spec §4). HTTP puro — roda na
fase de streaming sem sessão de banco (ADR-0020). O token do usuário viaja
SÓ no header; nunca é logado."""

import json
import logging
from dataclasses import dataclass

import httpx

from src.support.core.exceptions import DomainError, ExternalServiceUnavailableError
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

_PUBLIC_TARGET_KEYS = ("id", "path", "labelKey", "label")
_PUBLIC_SIGNAL_KEYS = ("matchedTags", "inProgress", "difficulty", "fallback")


class NavigationValidationError(DomainError):
    def __init__(self, message: str, valid_destinations: list[str]) -> None:
        super().__init__(message)
        self.valid_destinations = valid_destinations


class NavigationUnauthorizedError(DomainError):
    """Token da plataforma recusado pela API de navegação."""


def _pick(d: dict, keys: tuple[str, ...]) -> dict:
    return {k: d[k] for k in keys if k in d and d[k] is not None}


@dataclass(frozen=True)
class NavigationResult:
    destination: dict
    access: str
    unlock: dict | None
    signals: dict
    alternatives: list[dict]

    def to_public(self) -> dict:
        """Projeção que atravessa o redator (regra 4): sem `profile`, sem extras."""
        return {
            "destination": _pick(self.destination, _PUBLIC_TARGET_KEYS),
            "access": self.access,
            "unlock": dict(self.unlock) if self.unlock else None,
            "signals": _pick(self.signals, _PUBLIC_SIGNAL_KEYS),
            "alternatives": [_pick(a, _PUBLIC_TARGET_KEYS) for a in self.alternatives],
        }

    def to_tool_text(self) -> str:
        """O que o modelo lê: inclui `signals.profile` para frasear a resposta."""
        return json.dumps(
            {"destination": self.destination, "access": self.access, "unlock": self.unlock,
             "signals": self.signals, "alternatives": self.alternatives},
            ensure_ascii=False,
        )


class BorderlessNavigationClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{settings.BORDERLESS_AUTH_URL.rstrip('/')}{path}"

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=settings.NAVIGATION_TIMEOUT_SECONDS)

    async def resolve(self, access_token: str, destination: str, topic: str | None = None, goal: str | None = None) -> NavigationResult:
        body: dict = {"destination": destination}
        if topic:
            body["topic"] = topic
        if goal:
            body["goal"] = goal
        try:
            async with self._http() as client:
                response = await client.post(
                    self._url("/api/navigation/resolve"), json=body,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("navigation/resolve falhou na rede: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc

        if response.status_code == 400:
            error = _error_of(response)
            valid = error.get("details", {}).get("validDestinations") or []
            raise NavigationValidationError(error.get("message") or "destino inválido", [str(v) for v in valid])
        if response.status_code in (401, 403):
            raise NavigationUnauthorizedError("token recusado pela API de navegação")
        if response.status_code != 200:
            logger.warning("navigation/resolve devolveu %s", response.status_code)
            raise ExternalServiceUnavailableError("plataforma indisponível")
        try:
            data = response.json()["data"]
            return NavigationResult(
                destination=dict(data["destination"]), access=str(data["access"]),
                unlock=dict(data["unlock"]) if data.get("unlock") else None,
                signals=dict(data.get("signals") or {}), alternatives=list(data.get("alternatives") or []),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("navigation/resolve 200 fora do contrato: %s", type(exc).__name__)
            raise ExternalServiceUnavailableError("resposta fora do contrato") from exc

    async def catalog(self, access_token: str) -> list[dict]:
        try:
            async with self._http() as client:
                response = await client.get(self._url("/api/navigation/catalog"), headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise ExternalServiceUnavailableError("plataforma indisponível") from exc
        if response.status_code != 200:
            raise ExternalServiceUnavailableError(f"catalog devolveu {response.status_code}")
        try:
            return [dict(e) for e in response.json()["data"]["destinations"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceUnavailableError("catalog fora do contrato") from exc


def _error_of(response: httpx.Response) -> dict:
    try:
        return dict(response.json().get("error") or {})
    except ValueError:
        return {}
```

- [ ] **Step 4: Snapshot + catalog cache**

`navigation_catalog_snapshot.json`: the 17 entries exactly as `borderless-api/src/config/navigation-catalog.ts` defines them (`id, kind, path, labelKey, description, fallbackId?`). Copy the descriptions verbatim from that file.

```python
# src/support/agent/navigation_catalog.py
"""Catálogo de destinos que o modelo lê na descrição da tool navigate_platform.

A API exige token de usuário, então o catálogo é buscado com o token do turno
corrente e cacheado por processo (NAVIGATION_CATALOG_TTL_S). Sem token ou com a
API fora, vale o snapshot embutido — a API continua sendo a fonte da verdade:
um id fora do catálogo dela volta como 400 com `validDestinations`."""

import json
import logging
import time
from pathlib import Path
from typing import Callable

from src.support.clients.borderless.borderless_navigation_client import BorderlessNavigationClient
from src.support.core.settings import settings

logger = logging.getLogger(__name__)
_SNAPSHOT = Path(__file__).with_name("navigation_catalog_snapshot.json")


class NavigationCatalog:
    _cache: dict | None = None  # {"at": float, "entries": list[dict]} — por processo

    def __init__(self, client: BorderlessNavigationClient | None = None, clock: Callable[[], float] | None = None) -> None:
        self._client = client or BorderlessNavigationClient()
        self._clock = clock or time.monotonic

    @classmethod
    def reset(cls) -> None:
        cls._cache = None

    @staticmethod
    def snapshot() -> list[dict]:
        return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))

    @classmethod
    def snapshot_ids(cls) -> list[str]:
        return [e["id"] for e in cls.snapshot()]

    async def entries(self, access_token: str | None) -> list[dict]:
        cache = type(self)._cache
        if cache and self._clock() - cache["at"] < settings.NAVIGATION_CATALOG_TTL_S:
            return cache["entries"]
        if not access_token:
            return self.snapshot()
        try:
            entries = await self._client.catalog(access_token)
        except Exception:  # snapshot cobre; a API segue sendo a fonte da verdade
            logger.warning("catálogo de navegação indisponível; usando snapshot", exc_info=True)
            return self.snapshot()
        type(self)._cache = {"at": self._clock(), "entries": entries}
        return entries

    async def ids(self, access_token: str | None) -> list[str]:
        return [e["id"] for e in await self.entries(access_token)]

    async def describe(self, access_token: str | None) -> str:
        return "\n".join(f"- {e['id']} ({e['kind']}): {e['description']}" for e in await self.entries(access_token))
```

`tests/fakes/fake_navigation_client.py`:

```python
from src.support.clients.borderless.borderless_navigation_client import NavigationResult


class FakeNavigationClient:
    """`results` por destination id: NavigationResult ou Exception a lançar.
    `catalog`: lista de entradas ou Exception."""

    def __init__(self, results: dict, catalog=None) -> None:
        self._results = results
        self._catalog = catalog
        self.calls: list[dict] = []

    async def resolve(self, access_token, destination, topic=None, goal=None) -> NavigationResult:
        self.calls.append({"op": "resolve", "token": access_token, "destination": destination, "topic": topic, "goal": goal})
        outcome = self._results.get(destination)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            raise KeyError(f"sem resultado fake para {destination}")
        return outcome

    async def catalog(self, access_token) -> list[dict]:
        self.calls.append({"op": "catalog", "token": access_token})
        if isinstance(self._catalog, Exception):
            raise self._catalog
        return list(self._catalog or [])
```

Settings: `NAVIGATION_CATALOG_TTL_S: int = 3600`, `NAVIGATION_TIMEOUT_SECONDS: float = 8.0`; `.env.example` gets a commented `# --- Navegação (agente) ---` block with both.

- [ ] **Step 5: Run** `uv run pytest tests/unit/support -q` → PASS.

- [ ] **Step 6: Commit** `git commit -m "feat(navegacao): cliente da API de navegação e catálogo com cache e snapshot"`

---

### Task 6: `navigate` node, tool declaration, edge, redactor projection

**Files:**
- Create: `src/support/agent/graph/navigate_node.py`
- Modify: `src/support/agent/tools.py` (`build_tools(navigation_catalog_text: str | None = None)` + `navigate_platform` declaration; `TOOL_NODE_TOOLS`), `src/support/agent/graph/builder.py`, `src/support/agent/graph/edges.py` (`after_answer`), `src/support/agent/graph/nodes.py` (`_answer_model` binds catalog text from config), `src/support/agent/graph/runner.py` (`_STEP_NODES`, `_STATE_KEYS`, `_project`), `src/support/agent/ports.py` (`navigation_of`, `TurnSignals.navigation_called/navigation_access`, `NavigationResolverPort`)
- Test: `tests/unit/support/agent/graph/test_navigate_node.py`, `test_edges.py`, `test_runner.py` (redactor + full tool loop with a navigate call), `tests/unit/support/agent/test_tools.py` (if present; else create)

**Interfaces:**
- Consumes: `NavigationResult`, `NavigationValidationError`, `NavigationUnauthorizedError`, `FakeNavigationClient` (Task 5); `configurable["platform_token"]`, `configurable["navigation_client"]` (optional injection, default `BorderlessNavigationClient()`), `configurable["navigation_catalog_text"]`.
- Produces:
  - `NAVIGATE_TOOL_NAME = "navigate_platform"`; `navigate_platform(destination: str, topic: str | None = None, goal: Literal["learn","practice","network","interview","manage_account"] | None = None)` declared via `@tool` with a docstring `NAVIGATE_TOOL_DOC.format(catalog=...)`; its body raises `RuntimeError("navigate_platform é executada pelo nó navigate")` (never runs).
  - `build_tools(navigation_catalog_text=None) -> list` returns `[web_search, fetch_notion_page, navigate_platform]`; `TOOL_NODE_TOOLS = [web_search, fetch_notion_page]` for the `ToolNode`.
  - `navigate_node(state, config) -> dict`: reads the last `AIMessage`; for each tool call: if name is `navigate_platform` and `state["navigation"] is None` → resolve → `ToolMessage(content=wrap_tool_content(result.to_tool_text()), tool_call_id=..., name=...)`, sets `navigation = result.to_public()`; second navigate call in the same turn → `ToolMessage(status="error", content=wrap_tool_content("(uma navegação por turno — explique o destino já resolvido)"))`; any other tool call in the same message → `ToolMessage(status="error", content=wrap_tool_content("(chame uma ferramenta por vez)"))`. Errors: `NavigationValidationError` → error ToolMessage listing `valid_destinations`; `NavigationUnauthorizedError`/`ExternalServiceUnavailableError`/any Exception → error ToolMessage `"(falha ao resolver a navegação: plataforma indisponível)"`, logged. Signals: `tool_calls += 1` per navigate call, `navigation_called = True`, `navigation_access = result.access` on success. Returns `{"messages": [...], "navigation": <public or unchanged>}`.
  - `after_answer(state) -> Literal["navigate","tools","__end__"]`: last message has no tool calls → `END`; any call named `navigate_platform` → `"navigate"`; else `"tools"`.
  - Redactor: `_STEP_NODES` includes `"navigate"`; `_STATE_KEYS` includes `"intent"`; `_project` copies `navigation` through `_project_navigation()` (allowlist: `destination{id,path,labelKey,label}`, `access`, `unlock{action,path,membership}`, `signals{matchedTags,inProgress,difficulty,fallback}`, `alternatives[]` same keys) when present and not None.
  - `ports.navigation_of(event) -> dict | None`: from the `updates` chunk key `navigate` (`{"navigation": {...}}`) or from the root `on_chain_end` output.
  - `TurnSignals.navigation_called: bool = False`, `navigation_access: str | None = None`.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/support/agent/graph/test_navigate_node.py
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.support.agent.graph.navigate_node import navigate_node
from src.support.agent.ports import TurnSignals
from src.support.clients.borderless.borderless_navigation_client import (
    NavigationResult, NavigationUnauthorizedError, NavigationValidationError,
)
from tests.fakes.fake_navigation_client import FakeNavigationClient

RESULT = NavigationResult(
    destination={"id": "code_breakers", "path": "/code-breakers", "labelKey": "navigation.destinations.code_breakers"},
    access="allowed", unlock=None,
    signals={"matchedTags": [], "inProgress": False, "difficulty": None, "fallback": False,
             "profile": {"membership": "FREE", "seniority": "JUNIOR", "careerStage": "junior_transition"}},
    alternatives=[],
)


def _call(name="navigate_platform", args=None, id="call-1"):
    return {"name": name, "args": args or {"destination": "code_breakers"}, "id": id, "type": "tool_call"}


def _state(calls, navigation=None):
    return {"messages": [AIMessage(content="", tool_calls=calls)], "navigation": navigation}


def _config(client, signals=None):
    return {"configurable": {"signals": signals or TurnSignals(), "platform_token": "tok", "navigation_client": client}}


@pytest.mark.asyncio
async def test_resolve_a_navegacao_e_projeta_no_state():
    client = FakeNavigationClient({"code_breakers": RESULT})
    signals = TurnSignals()
    out = await navigate_node(_state([_call()]), _config(client, signals))
    assert client.calls[0]["token"] == "tok" and client.calls[0]["destination"] == "code_breakers"
    msg = out["messages"][0]
    assert isinstance(msg, ToolMessage) and msg.tool_call_id == "call-1" and msg.status == "success"
    assert "<<TOOL_CONTENT>>" in msg.content and '"profile"' in msg.content
    assert out["navigation"] == RESULT.to_public()
    assert "profile" not in out["navigation"]["signals"]
    assert signals.tool_calls == 1 and signals.navigation_called is True and signals.navigation_access == "allowed"


@pytest.mark.asyncio
async def test_segunda_navegacao_no_mesmo_turno_e_recusada():
    client = FakeNavigationClient({"code_breakers": RESULT})
    out = await navigate_node(_state([_call()], navigation=RESULT.to_public()), _config(client))
    assert client.calls == []
    assert out["messages"][0].status == "error" and "uma navegação por turno" in out["messages"][0].content
    assert out["navigation"] == RESULT.to_public()


@pytest.mark.asyncio
async def test_destino_invalido_devolve_erro_com_ids_validos_e_nao_navega():
    client = FakeNavigationClient({"moon": NavigationValidationError("Unknown", ["home", "trails"])})
    out = await navigate_node(_state([_call(args={"destination": "moon"})]), _config(client))
    msg = out["messages"][0]
    assert msg.status == "error" and "home" in msg.content and "trails" in msg.content
    assert out["navigation"] is None


@pytest.mark.asyncio
async def test_plataforma_fora_ou_token_recusado_nao_derruba_o_turno():
    client = FakeNavigationClient({"code_breakers": NavigationUnauthorizedError("no")})
    out = await navigate_node(_state([_call()]), _config(client))
    assert out["messages"][0].status == "error" and "(falha ao resolver a navegação" in out["messages"][0].content
    assert out["navigation"] is None


@pytest.mark.asyncio
async def test_outras_tools_na_mesma_mensagem_recebem_erro_e_a_navegacao_roda():
    client = FakeNavigationClient({"code_breakers": RESULT})
    calls = [_call(id="c1"), _call(name="web_search", args={"query": "x"}, id="c2")]
    out = await navigate_node(_state(calls), _config(client))
    by_id = {m.tool_call_id: m for m in out["messages"]}
    assert by_id["c1"].status == "success" and by_id["c2"].status == "error"
    assert out["navigation"] == RESULT.to_public()
```

`test_edges.py`:

```python
from langchain_core.messages import AIMessage
from langgraph.graph import END
from src.support.agent.graph.edges import after_answer

def test_after_answer_routes_navigate_calls_to_the_navigate_node():
    msg = AIMessage(content="", tool_calls=[{"name": "navigate_platform", "args": {"destination": "home"}, "id": "1", "type": "tool_call"}])
    assert after_answer({"messages": [msg]}) == "navigate"

def test_after_answer_routes_other_tool_calls_to_tools():
    msg = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "q"}, "id": "1", "type": "tool_call"}])
    assert after_answer({"messages": [msg]}) == "tools"

def test_after_answer_ends_without_tool_calls():
    assert after_answer({"messages": [AIMessage(content="pronto")]}) == END
```

`test_runner.py` (redactor + loop): a `_project` test where the state has `navigation` with an extra key `profile` inside `signals` and an extra top-level key → projected output keeps only the allowlist; an end-to-end run with `ScriptedChatModel` replying first `AIMessage(content="", tool_calls=[navigate_platform → code_breakers])` then `AIMessage(content="Te levei para o CodeBreakers")`, `mode="navigate"`, `extra_config={"platform_token": "tok", "navigation_client": FakeNavigationClient({...})}`, `enable_tools=True`: assert steps include `("navigate","start"),("navigate","end")`, an `updates` chunk `{"navigate": {"navigation": {...}}}` appears BEFORE the first `on_chat_model_stream` token of the final sentence, `navigation_of(root_end) == RESULT.to_public()`, no forbidden keys (`FORBIDDEN_KEYS ∪ {"platform_token", "profile"}`) anywhere in the serialized events.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement**

`ports.py`:

```python
class NavigationResolverPort(Protocol):
    async def resolve(self, access_token: str, destination: str, topic: str | None = None, goal: str | None = None): ...


def navigation_of(event: GraphEvent) -> dict | None:
    """O destino resolvido: no chunk `updates` do nó `navigate` (antes do modelo
    terminar a frase) e, repetido, no `on_chain_end` do raiz."""
    updates = _updates_chunk(event)
    if updates is not None:
        nav = (updates.get("navigate") or {}).get("navigation")
        return dict(nav) if nav else None
    if event.event == "on_chain_end" and event.is_root:
        nav = (event.data.get("output") or {}).get("navigation")
        return dict(nav) if nav else None
    return None
```

`TurnSignals` adds `navigation_called: bool = False`, `navigation_access: str | None = None`.

`tools.py`:

```python
NAVIGATE_TOOL_NAME = "navigate_platform"
NAVIGATE_TOOL_DOC = """Leva o usuário a um destino da Borderless Platform. Use quando ele quer IR a
um lugar, ENCONTRAR um conteúdo ou COMEÇAR uma atividade. A resolução do destino
concreto e do acesso é feita pela plataforma a partir do perfil do usuário.

destination: um id do catálogo abaixo. topic: tema livre quando houver (ex.:
"backend node.js", "system design", "python"). goal: learn | practice | network |
interview | manage_account.

Catálogo:
{catalog}
"""


def build_tools(navigation_catalog_text: str | None = None) -> list:
    ... web_search, fetch_notion_page como hoje ...

    catalog = navigation_catalog_text or NavigationCatalog.snapshot_text()

    @tool(NAVIGATE_TOOL_NAME, description=NAVIGATE_TOOL_DOC.format(catalog=catalog))
    async def navigate_platform(
        destination: str,
        topic: str | None = None,
        goal: Literal["learn", "practice", "network", "interview", "manage_account"] | None = None,
    ) -> str:
        raise RuntimeError("navigate_platform é executada pelo nó navigate, não pelo ToolNode")

    return [web_search, fetch_notion_page, navigate_platform]


def tool_node_tools() -> list:
    """Só as tools que o ToolNode executa — navigate_platform vai ao nó próprio."""
    return [t for t in build_tools() if t.name != NAVIGATE_TOOL_NAME]
```

(`NavigationCatalog.snapshot_text()` = the `describe` formatting applied to the snapshot; add it as a `@classmethod` in Task 5's module.)

`nodes.py` `_answer_model`: `model.bind_tools(build_tools(cfg.get("navigation_catalog_text")))`.

`navigate_node.py`:

```python
"""Nó `navigate`: executa navigate_platform fora do ToolNode para que o destino
entre no state (`navigation`) e saia no chunk `updates` antes da frase final
(spec §5.3). HTTP-only: roda na fase stream (ADR-0020)."""

import logging

from langchain_core.messages import AIMessage, ToolMessage

from src.support.agent.graph.state import TurnState
from src.support.agent.tools import NAVIGATE_TOOL_NAME, wrap_tool_content
from src.support.clients.borderless.borderless_navigation_client import (
    BorderlessNavigationClient, NavigationValidationError,
)

logger = logging.getLogger(__name__)


def _last_ai_message(state: TurnState) -> AIMessage | None:
    for message in reversed(state.get("messages") or []):
        if isinstance(message, AIMessage):
            return message
    return None


def _error(call, text: str) -> ToolMessage:
    return ToolMessage(content=wrap_tool_content(text), tool_call_id=call["id"], name=call["name"], status="error")


async def navigate_node(state: TurnState, config) -> dict:
    cfg = config["configurable"]
    signals = cfg["signals"]
    client = cfg.get("navigation_client") or BorderlessNavigationClient()
    token = cfg.get("platform_token")

    message = _last_ai_message(state)
    navigation = state.get("navigation")
    out: list[ToolMessage] = []

    for call in (message.tool_calls if message else []):
        if call["name"] != NAVIGATE_TOOL_NAME:
            out.append(_error(call, "(chame uma ferramenta por vez: a navegação já foi solicitada neste turno)"))
            continue
        signals.tool_calls += 1
        signals.navigation_called = True
        if navigation is not None:
            out.append(_error(call, "(uma navegação por turno — explique o destino já resolvido)"))
            continue
        if not token:
            out.append(_error(call, "(falha ao resolver a navegação: sessão sem token da plataforma)"))
            continue
        args = call.get("args") or {}
        try:
            result = await client.resolve(token, str(args.get("destination", "")), topic=args.get("topic"), goal=args.get("goal"))
        except NavigationValidationError as exc:
            out.append(_error(call, f"(destino inválido; use um destes ids: {', '.join(exc.valid_destinations)})"))
            continue
        except Exception:
            logger.warning("navigate_platform falhou", exc_info=True)
            out.append(_error(call, "(falha ao resolver a navegação: plataforma indisponível)"))
            continue
        navigation = result.to_public()
        signals.navigation_access = result.access
        out.append(ToolMessage(content=wrap_tool_content(result.to_tool_text()), tool_call_id=call["id"], name=call["name"]))

    return {"messages": out, "navigation": navigation}
```

`edges.py`:

```python
def after_answer(state: TurnState) -> Literal["navigate", "tools", "__end__"]:
    message = state["messages"][-1] if state.get("messages") else None
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return END
    if any(call["name"] == NAVIGATE_TOOL_NAME for call in calls):
        return "navigate"
    return "tools"
```

`builder.py`: `builder.add_node("tools", ToolNode(tool_node_tools()))`, `builder.add_node("navigate", navigate_node)`, replace `tools_condition` with `after_answer` mapping `{"navigate": "navigate", "tools": "tools", END: END}`, `builder.add_edge("navigate", "answer")`.

`runner.py`: `_STEP_NODES = frozenset({"gate", "retrieve", "refuse", "answer", "navigate"})`; `_STATE_KEYS = ("retrieve", "degraded", "answer", "outcome", "intent")`; in `_project`: `if state.get("navigation"): out["navigation"] = _project_navigation(state["navigation"])` with the key allowlist above. Note `_answer_started` guard: the tool loop re-enters `answer`; unchanged.

- [ ] **Step 4: Run** `uv run pytest tests/unit/support/agent -q` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(turno): nó navigate executa navigate_platform e projeta o destino no fio"`

---

### Task 7: Prompt — NAVEGAÇÃO block, profile and locale in the answer prompt

**Files:**
- Modify: `src/support/agent/prompts.py`, `src/support/agent/graph/nodes.py` (`_answer_messages(state, config)`)
- Test: `tests/unit/support/agent/graph/test_nodes.py` (prompt assembly), `tests/unit/support/agent/test_prompts.py` (create: block present, no contradiction markers)

**Interfaces:**
- Consumes: `configurable["user_profile"] = {"membership","seniority","careerStage"}`, `state["locale"]`, `state["intent"]`, `state["mode"]`.
- Produces: `SYSTEM_PROMPT` with a `NAVEGAÇÃO` section and an explicit exception to rule 1 for `navigate`/`chit_chat`; `_answer_messages` appends `Perfil do usuário: membership=…, seniority=…, careerStage=…` and `Idioma da resposta: <locale>` and, when `intent == "navigate"`, `Intenção: navegação (não use a RESPOSTA PADRÃO)`.

- [ ] **Step 1: Failing tests** — `_answer_messages({"question": "q", "history": [], "knowledge": [], "locale": "en", "intent": "navigate"}, {"configurable": {"user_profile": {"membership": "FREE", "seniority": "JUNIOR", "careerStage": "junior_transition"}}})` → the human message contains `"Idioma da resposta: en"`, `"membership=FREE"`, `"Intenção: navegação"`; with `intent="knowledge"` it does not contain `"Intenção: navegação"`. `SYSTEM_PROMPT` contains `"navigate_platform"` and `"Nunca invente destinos"`.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement** — append to `SYSTEM_PROMPT`:

```
NAVEGAÇÃO:
- Quando o usuário quer IR a um lugar da plataforma, ENCONTRAR um conteúdo ou
  COMEÇAR uma atividade, chame `navigate_platform` com um `destination` do
  catálogo (e `topic` quando houver tema). Use o Perfil do usuário fornecido
  para escolher: junior_transition → trilha (`trail`); mid_senior_internationalize
  → programas de mock interview (`program`); already_global → `events` / `forum`;
  curious → `home`. Sem destino claro, faça UMA pergunta de esclarecimento e
  não chame a ferramenta.
- Depois do resultado: responda em UMA frase, no idioma indicado em "Idioma da
  resposta", dizendo para onde levou e por quê (use `signals`: matchedTags,
  inProgress, difficulty). Se `access` não for "allowed", explique o bloqueio e
  ofereça exatamente o `unlock` devolvido; sem `unlock`, apenas explique.
- Nunca invente destinos, caminhos ou nomes de trilha. Uma navegação por turno.
- Intenção de navegação ou conversa NÃO exige contexto da base: a regra 1 e a
  RESPOSTA PADRÃO valem só para perguntas substantivas sobre o ecossistema.
  Em "Intenção: navegação" sem destino identificável, responda em uma frase e
  sugira abrir o chat — nunca use a RESPOSTA PADRÃO.
```

Amend rule 1 to read "Para perguntas substantivas sobre o ecossistema, responda SOMENTE com base…". `_answer_messages(state, config)` builds the extra lines from `config["configurable"].get("user_profile")` (skip the line when absent) and `state.get("locale", "pt-BR")`; `answer_node` passes `config`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/support/agent -q` → PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(prompt): bloco de navegação, perfil e idioma no prompt do oráculo"`

---

### Task 8: Persist `navigation` on messages and trace columns

**Files:**
- Create: `database/migrations/versions/0011_navigation_persistence.py`
- Modify: `src/domain/conversations/models/message.py`, `entities/message.py`, `mappers/message_mapper.py`, `actions/append_assistant_message_action.py`
- Modify: `src/domain/observability/dtos/turn_trace_draft.py`, `entities/turn_trace.py`, `models/turn_trace.py`, `mappers/turn_trace_mapper.py`
- Modify: `src/app/api/responses/conversation_responses.py` (`MessageResponse.navigation: dict | None`)
- Test: `tests/unit/domain/conversations/mappers/test_message_mapper.py`, `tests/unit/domain/observability/mappers/*`, `tests/unit/domain/observability/dtos/*`, `tests/integration/domain/conversations/*` (append with navigation round-trips)

**Interfaces:**
- Produces: `Message.navigation: dict | None = None`; `AppendAssistantMessageAction.execute(conversation_id, content, citations, navigation=None)`; `TurnTraceDraft.intent: str | None = None`, `.navigation_called: bool = False`, `.navigation_access: str | None = None` (and the same on `TurnTrace`, `TurnTraceModel` as `String(16) nullable`, `Boolean default False`, `String(16) nullable`, and in `_FLAT_FIELDS`); `MessageResponse.navigation`.

- [ ] **Step 1: Failing tests** — mapper round-trip with `navigation={"destination": {...}, "access": "allowed", ...}` and with `None`; draft `to_entity` carries the three fields; `MessageResponse.from_entity` exposes `navigation`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Migration**

```python
"""messages.navigation e colunas de navegação no agent_traces (spec §5.5).

Revision ID: 0011_navigation_persistence
Revises: 0010_sessions_bearer_profile
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_navigation_persistence"
down_revision = "0010_sessions_bearer_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("navigation", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_traces", sa.Column("intent", sa.String(16), nullable=True))
    op.add_column("agent_traces", sa.Column("navigation_called", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("agent_traces", sa.Column("navigation_access", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_traces", "navigation_access")
    op.drop_column("agent_traces", "navigation_called")
    op.drop_column("agent_traces", "intent")
    op.drop_column("messages", "navigation")
```

Then the model/entity/mapper/action/response edits listed above (mapper copies `navigation` as-is; it is already a public projection).

- [ ] **Step 4: Run** `uv run pytest tests/unit/domain tests/unit/app -q` → PASS; integration tests after `uv run alembic upgrade head`.
- [ ] **Step 5: Commit** `git commit -m "feat(persistencia): navigation na mensagem do assistente e no trace do turno"`

---

### Task 9: Controller wiring — token, profile, catalog, capture, trace

**Files:**
- Modify: `src/app/api/controllers/conversation_controller.py`
- Modify: `tests/fakes/fake_turn_graph.py` (option `navigation=` emitting `updates("navigate", {"navigation": …})`, `node start/end "navigate"`, and `navigation` in the root end), `tests/fakes/stream_events.py` (`navigation_of(evs)`)
- Test: `tests/integration/api/test_ask_endpoint.py` (new cases), `tests/integration/api/test_ask_trace_persistence.py` (trace columns)

**Interfaces:**
- Consumes: `AuthenticatedUser.platform_access_token/membership/seniority/career_stage`; `NavigationCatalog.describe(token)`; `navigation_of`; `OpenTurnAction(mode, locale)`; `RunTurnAction.execute(turn, extra_config)`; `AppendAssistantMessageAction(..., navigation)`.
- Produces: `ask()` builds `extra_config = {"platform_token": user.platform_access_token, "user_profile": {"membership": user.membership, "seniority": user.seniority, "careerStage": user.career_stage}, "navigation_catalog_text": await NavigationCatalog().describe(user.platform_access_token)}`; captures `navigation_of(event)` into `captured["navigation"]`; `_persist_turn(..., navigation)`; `_absorb_engine_metrics` copies `intent`, `navigation_called`, `navigation_access` from signals.

- [ ] **Step 1: Failing integration tests** — with `FakeTurnGraph(navigation=RESULT_PUBLIC)` and `ask_body("quero praticar algoritmos", mode="navigate", locale="en")`: the SSE contains an `updates` chunk with `navigate.navigation.destination.path == "/code-breakers"` BEFORE any `on_chat_model_stream`; `root_end["data"]["output"]["navigation"]` equals it; `GET /conversations/{id}` returns the assistant message with `navigation` set; `agent_traces` row has `intent == "navigate"`, `navigation_called is True`, `navigation_access == "allowed"`; `FakeTurnGraph.received_mode == "navigate"`, `received_locale == "en"`, and `received_extra_config["platform_token"]` equals the seeded session's platform token. A second test with the default body keeps `navigation is None` everywhere.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — `NavigationCatalog.describe` runs in the request scope (HTTP only, before the SSE body); wrap it in `try/except Exception` → snapshot text via `NavigationCatalog.snapshot_text()` so a catalog hiccup never blocks a turn. `FakeTurnGraph.run` stores `received_extra_config`, `received_mode`, `received_locale`.
- [ ] **Step 4: Run** `uv run pytest tests/integration/api -q` → PASS (Postgres up).
- [ ] **Step 5: Commit** `git commit -m "feat(api): /conversations/ask leva token, perfil e catálogo ao grafo e persiste a navegação"`

---

### Task 10: Evals — `navigation` category with a deterministic metric

**Files:**
- Modify: `evals/models.py` (category `navigation`, field `expected_destination`, metric `NAVIGATION_TARGET = "navigation_target"`, `metrics_for_category("navigation") == (NAVIGATION_TARGET,)`), `evals/runner.py` (collect `navigation_of` during the run; score `navigation_target` locally: `1.0` if `navigation["destination"]["id"] == expected_destination` and the refusal opening is absent, else `0.0`; judge is not called for this category), `evals/report.py` (`DEFAULT_THRESHOLDS[NAVIGATION_TARGET] = 0.9`, `HARD_FAIL_CATEGORIES += ("navigation",)`), `evals/__main__.py` (pass `extra_config={"platform_token": "eval", "navigation_client": FakeNavigationClient(...)}` built from `evals/cases/navigation_fixtures.json`, and `mode="navigate"` when the case has `mode`)
- Create: `evals/cases/navigation_set.json` (≥ 8 cases: bar-mode "quero praticar algoritmos"→`code_breakers`, "me leva para as trilhas de backend"→`trail`, "onde vejo meus eventos?"→`events`, "quero treinar system design"→`program`, "quero trocar o idioma"→`settings`, "ver minhas compras"→`settings_purchases`, chat-mode "how do I get to the leaderboard?"→`leaderboard`, and one ambiguous "quero melhorar" with `expected_destination: null` meaning no navigation must happen), `evals/cases/navigation_fixtures.json` (canned `NavigationResult` per destination id)
- Test: `tests/unit/evals/test_models.py` (loading validation), `tests/unit/evals/test_runner_navigation.py` (scoring with a `FakeTurnGraph` that emits navigation)

- [ ] Steps: failing tests → implement → `uv run pytest tests/unit/evals -q` → `uv run python -m evals --dry-run` prints the new category count → commit `git commit -m "feat(evals): categoria navigation com métrica determinística de destino"`.

---

### Task 11: Documentation — ADR-0022, CLAUDE.md, architecture, env

**Files:**
- Create: `docs/adr/ADR-0022-navigation-tool.md` (context: spec; decision: dedicated `navigate` node instead of ToolNode so the destination is projected and streamed early; bearer sessions sharing the `sessions` table; catalog fetched per turn with user token + snapshot fallback — deviation from spec §5.4 "cache 1h at boot" because the catalog endpoint requires a user token; one navigation per turn; consequences and alternatives)
- Modify: `CLAUDE.md` "Stack principal" (Agente de IA: mention `navigate` node and `mode/locale` inputs; Autenticação: bearer path), `docs/architecture.md` (graph diagram + auth section), `.env.example` (done in Task 5 — verify), `docs/as_stream.md` (add the `navigate` step and the `navigation` projection to the wire description)
- Note the manual step from spec §5.4 last bullet: create the "Mapa da plataforma" page in Notion (approved) from the video transcript so the Oracle can explain areas with citations.

- [ ] Write, self-check links, commit `git commit -m "docs(adr): ADR-0022 — tool de navegação, sessões por bearer e catálogo por turno"`.

---

## Self-review notes

- Spec §3 flow: steps 2–7 → Tasks 2, 3, 4, 6, 7, 9. §5.1 → Tasks 1–2 (with the profile-snapshot addition). §5.2 → Task 3. §5.3 → Tasks 3, 4, 6. §5.4 → Tasks 5, 7 (catalog fetched per turn with the user's token instead of at boot — documented in ADR-0022). §5.5 → Tasks 6, 8, 9, 10. §5.6 (Oracle SPA) intentionally untouched: the SPA's `isStepNode` ignores the unknown `navigate` step and `navigation` payloads, so it keeps working.
- Names consistent across tasks: `NavigationResult`, `to_public()`, `to_tool_text()`, `NavigationValidationError.valid_destinations`, `NavigationCatalog.describe/ids/snapshot_text/snapshot_ids/reset`, `NAVIGATE_TOOL_NAME`, `navigate_node`, `after_answer`, `navigation_of`, `TurnSignals.intent/navigation_called/navigation_access`, `configurable["platform_token"|"navigation_client"|"user_profile"|"navigation_catalog_text"]`, `OpenedTurn.mode/locale`, `RunTurnAction.execute(turn, extra_config)`.
- Regra 4 checked: token only in `configurable`; `navigation` projected via allowlist; `profile` excluded from the wire and present only in the tool text the model reads.
