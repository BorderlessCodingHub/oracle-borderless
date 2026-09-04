"""IMPORTANT 6: a exigência de auth em `router` deixou de ser convenção e virou
mecânica (ADR-0017/0018) — `_include_module_routers` amarra `Depends(require_user)`
em qualquer módulo que exponha `router`, mesmo que o módulo tenha esquecido de
declarar isso sozinho."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.middlewares import DBSessionMiddleware
from src.app.api.routes import _include_module_routers


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine():
    yield
    from src.support.core.database import engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_router_de_um_modulo_hipotetico_sai_protegido_mesmo_sem_dependency_propria():
    """Um módulo novo que só faz `router = APIRouter()` e esquece de proteger
    a rota — hoje isso vazaria público por convenção quebrada. Depois da
    mudança, `_include_module_routers` amarra a auth na hora do include,
    então o endpoint 401 sem token mesmo sem nenhuma dependency explícita."""
    dummy_router = APIRouter()

    @dummy_router.get("/dummy-hipotetico")
    async def _dummy():
        return {"ok": True}

    dummy_module = SimpleNamespace(router=dummy_router)

    app = FastAPI()
    # require_user v2 (ADR-0018) resolve o cookie contra a tabela `sessions`:
    # o app hipotético precisa da mesma sessão de banco por request do app real.
    app.add_middleware(DBSessionMiddleware)
    _include_module_routers(app, dummy_module, "dummy_module")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sem_token = await client.get("/dummy-hipotetico")
        assert sem_token.status_code == 401

        from tests.fakes.auth import auth_headers

        com_token = await client.get("/dummy-hipotetico", headers=await auth_headers("a@x.com"))
        assert com_token.status_code == 200


@pytest.mark.asyncio
async def test_public_router_de_um_modulo_hipotetico_continua_sem_auth():
    """`public_router` é o opt-out explícito — não deve ganhar a dependency."""
    dummy_public = APIRouter()

    @dummy_public.get("/dummy-publico")
    async def _dummy():
        return {"ok": True}

    dummy_module = SimpleNamespace(public_router=dummy_public)

    app = FastAPI()
    _include_module_routers(app, dummy_module, "dummy_module")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/dummy-publico")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_app_real_health_publico_e_conversations_protegido():
    """Confirma no app de verdade (não só no módulo isolado) que a rota
    pública continua pública e a privada continua exigindo token — a
    combinação que a mudança não pode quebrar em nenhum dos dois sentidos."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200

        conversations = await client.get("/conversations")
        assert conversations.status_code == 401
