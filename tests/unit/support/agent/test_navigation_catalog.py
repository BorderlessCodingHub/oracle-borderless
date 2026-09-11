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


def test_snapshot_text_usa_o_mesmo_formato_de_describe():
    text = NavigationCatalog.snapshot_text()
    assert "trail (dynamic)" in text and "home (static)" in text
    assert text.count("\n") == 16


@pytest.mark.asyncio
async def test_uma_falha_e_cacheada_negativamente_e_nao_repete_a_chamada_dentro_do_retry():
    """R13: sem cache negativo, cada turno seguinte repagava a chamada (e o
    timeout dela) no caminho crítico enquanto a API estivesse fora."""
    now = {"t": 1000.0}
    client = FakeNavigationClient(results={}, catalog=ExternalServiceUnavailableError("fora"))
    catalog = NavigationCatalog(client=client, clock=lambda: now["t"])

    first = await catalog.describe("tok")
    now["t"] += 59
    second = await catalog.describe("tok")

    assert "trail (dynamic)" in first and second == first  # snapshot embutido nas duas
    assert len([c for c in client.calls if c["op"] == "catalog"]) == 1


@pytest.mark.asyncio
async def test_a_falha_cacheada_expira_no_retry_e_a_api_e_tentada_de_novo():
    now = {"t": 1000.0}
    client = FakeNavigationClient(results={}, catalog=ExternalServiceUnavailableError("fora"))
    catalog = NavigationCatalog(client=client, clock=lambda: now["t"])

    await catalog.describe("tok")
    now["t"] += 61
    await catalog.describe("tok")

    assert len([c for c in client.calls if c["op"] == "catalog"]) == 2


@pytest.mark.asyncio
async def test_a_volta_da_api_substitui_o_cache_negativo_pelo_catalogo_ao_vivo():
    now = {"t": 1000.0}
    client = FakeNavigationClient(results={}, catalog=ExternalServiceUnavailableError("fora"))
    catalog = NavigationCatalog(client=client, clock=lambda: now["t"])
    await catalog.describe("tok")

    now["t"] += 61
    back = NavigationCatalog(client=FakeNavigationClient(results={}, catalog=[ENTRY]), clock=lambda: now["t"])
    assert "code_breakers (static): Algorithm challenges" in await back.describe("tok")
