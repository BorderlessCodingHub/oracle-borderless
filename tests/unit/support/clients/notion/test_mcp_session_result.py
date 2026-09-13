"""Decodificação do resultado de uma tool MCP.

Os testes constroem o modelo REAL do SDK (`mcp.types.CallToolResult`) de
propósito: o sinal de erro se chama `is_error` no SDK 2.x, e um stub com o
nome antigo (`isError`) esconderia exatamente a quebra que derrubava toda
chamada ao Notion com `AttributeError`.
"""

import pytest
from mcp.types import CallToolResult, TextContent

from src.support.clients.notion.mcp_session import NotionMCPError, decode_tool_result


def _result(text: str, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)


def test_devolve_o_json_da_tool():
    assert decode_tool_result("API-post-search", _result('{"results": [1, 2]}')) == {
        "results": [1, 2]
    }


def test_resultado_vazio_vira_dict_vazio():
    assert decode_tool_result("API-post-search", _result("   ")) == {}


def test_erro_da_tool_vira_NotionMCPError_com_o_texto():
    result = _result("token inválido", is_error=True)

    with pytest.raises(NotionMCPError) as exc:
        decode_tool_result("API-post-search", result)

    assert "API-post-search" in str(exc.value)
    assert "token inválido" in str(exc.value)
