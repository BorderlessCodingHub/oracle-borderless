"""Sessão MCP com o servidor `@notionhq/notion-mcp-server` (ADR-0010).

Modo dev: transporte **stdio**, disparando o servidor via `npx`. O token da
integração vem de `settings.NOTION_MCP_TOKEN` e é injetado como `NOTION_TOKEN`
no processo do servidor. Abre uma sessão por operação (o `npx` sobe o servidor
a cada chamada — aceitável para CLI/ingestão; em produção o ADR prevê sidecar
HTTP reusando `NOTION_MCP_URL`).
"""

import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Awaitable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.support.core.settings import settings

# call(tool_name, arguments) -> dict (JSON já parseado do resultado da tool)
ToolCall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class NotionMCPError(RuntimeError):
    """Falha ao falar com o servidor MCP do Notion."""


def decode_tool_result(tool: str, result: Any) -> dict[str, Any]:
    """Texto do resultado de uma tool MCP -> dict.

    O sinal de erro é `result.is_error`: o SDK do MCP (2.x, ver o pin em
    pyproject) expõe o campo em snake_case e mantém `isError` apenas como
    alias de serialização, então ler o nome antigo levanta AttributeError em
    TODA chamada — inclusive nas bem-sucedidas. Vive fora do gerador para ser
    testável sem subir o servidor por `npx`.
    """
    text = "".join(getattr(block, "text", "") for block in result.content).strip()
    if result.is_error:
        raise NotionMCPError(f"tool {tool!r} retornou erro: {text[:300]}")
    if not text:
        return {}
    return json.loads(text)


@asynccontextmanager
async def notion_mcp_session() -> AsyncIterator[ToolCall]:
    """Abre uma sessão stdio com o notion-mcp-server e entrega um `call`."""
    token = settings.NOTION_MCP_TOKEN
    if not token or token.lstrip().startswith("#"):
        raise NotionMCPError(
            "NOTION_MCP_TOKEN não configurado no .env — preencha com o token da integração (ntn_…)."
        )

    params = StdioServerParameters(
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={**os.environ, "NOTION_TOKEN": token},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
                return decode_tool_result(tool, await session.call_tool(tool, arguments))

            yield call
