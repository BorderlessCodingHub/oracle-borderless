"""O nó `navigate`: executa `navigate_platform` fora do ToolNode para que o
destino entre no state antes da frase final (spec §5.3). Uma navegação por
turno; erro de plataforma vira ToolMessage de erro, nunca exceção."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.support.agent.graph.navigate_node import navigate_node
from src.support.agent.ports import TurnSignals
from src.support.clients.borderless.borderless_navigation_client import (
    NavigationResult,
    NavigationUnauthorizedError,
    NavigationValidationError,
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


@pytest.mark.asyncio
async def test_sem_token_da_plataforma_a_navegacao_falha_sem_chamar_a_api():
    """Sessão sem `platform_token`: o nó devolve erro ao modelo em vez de
    chamar a API com token vazio."""
    client = FakeNavigationClient({"code_breakers": RESULT})
    config = {"configurable": {"signals": TurnSignals(), "navigation_client": client}}
    out = await navigate_node(_state([_call()]), config)
    assert client.calls == []
    assert out["messages"][0].status == "error" and "(falha ao resolver a navegação" in out["messages"][0].content
    assert out["navigation"] is None
