# Oracle Borderless

A **"Claude Code"-style AI agent repositioned as an oracle**: a *single source of truth* queryable in natural language. Anyone asks a question in natural language and gets a useful, reliable, and friendly answer, based **exclusively on approved sources**.

## What it is

- **Knowledge base in Notion via MCP** (Model Context Protocol) — the agent consumes only released documents.
- **Natural-language questions** about the ecosystem's business rules and operational data (e.g., student results), with answers in plain language.
- **Nothing confidential** is ingested or exposed — content comes only from sources permitted by the Notion MCP's access restrictions.
- Built for **production**, with its own URL/domain and a product-like appearance.

## Stack

- **Framework:** FastAPI (Python 3.13+)
- **ORM:** SQLAlchemy 2.0 (async `asyncpg` + sync `psycopg`)
- **Migrations:** Alembic
- **Validation:** Pydantic v2
- **Knowledge base:** Notion via MCP
- **Scheduler:** APScheduler (PostgreSQL jobstore)
- **Package manager:** UV

## Architecture

**Spatie Laravel Beyond CRUD pattern adapted to FastAPI**, in three layers:

- `src/app/` — entry points (HTTP, console/jobs)
- `src/domain/` — business logic, organized by subdomain (bounded contexts)
- `src/support/` — cross-cutting tooling (infra, integrations, utils)

The web interface is a separate React + Vite SPA in [`frontend/`](frontend/), which talks to the backend over HTTP/SSE.

Start with **[`CLAUDE.md`](CLAUDE.md)** (rules and condensed overview) and **[`docs/architecture.md`](docs/architecture.md)** (full architecture).

## Running in development

```bash
# Start the application
uvicorn main:app --reload

# Migrations
alembic upgrade head

# Seeds
python -m database.seeds

# Tests
pytest
```

## Open questions

Still to be decided together (don't make assumptions): the **authentication layer** (there will be auth restricted to the ecosystem — Cloudflare Access at the edge is the leading candidate, pending confirmation with the product owner) and the production deployment (domain, how `frontend/dist` is served).

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full architecture
- [`docs/actions-vs-services.md`](docs/actions-vs-services.md) — Action vs Domain Service
- [`docs/conventions.md`](docs/conventions.md) — naming and style
- [`docs/adding-new-domain.md`](docs/adding-new-domain.md) — creating a new subdomain
- [`docs/database-guide.md`](docs/database-guide.md) — migrations, seeds, factories
- [`docs/testing-guide.md`](docs/testing-guide.md) — testing
- [`docs/scaffolding-guide.md`](docs/scaffolding-guide.md) — `make:*` commands
