"""Shape dos quatro endpoints de ops. Mesmo padrão dos outros testes de API:
ASGITransport contra o app real, banco de dev, engine descartada entre testes."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


@pytest_asyncio.fixture
async def ops_client():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_overview_returns_the_map_payload(ops_client):
    resp = await ops_client.get("/ops/overview?window=24h")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "24h"
    assert "documents_active" in body["knowledge"]
    assert "gate_retrieve" in body["traces"]
    assert body["rag_max_distance"] > 0
    assert body["rag_top_k"] > 0
    # sem run do sync, os campos vêm nulos em vez de estourar
    assert "status" in body["sync"]
    assert isinstance(body["knowledge_gaps"], list)


@pytest.mark.asyncio
async def test_overview_rejects_an_unknown_window(ops_client):
    assert (await ops_client.get("/ops/overview?window=42y")).status_code == 422


@pytest.mark.asyncio
async def test_turns_list_returns_a_list(ops_client):
    resp = await ops_client.get("/ops/turns?window=24h&limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_unknown_trace_is_404(ops_client):
    resp = await ops_client.get("/ops/turns/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_eval_reports_no_runs_when_there_is_no_report(ops_client, tmp_path, monkeypatch):
    from src.support.core.settings import settings

    monkeypatch.setattr(settings, "EVAL_REPORTS_DIR", str(tmp_path))
    resp = await ops_client.get("/ops/eval")
    assert resp.status_code == 200
    body = resp.json()
    # Envelope completo: as três chaves que o schema EvalReportResponse tranca.
    assert set(body.keys()) == {"status", "report", "history"}
    assert body["status"] == "no_runs"
    assert body["report"] is None
    assert body["history"] == []
