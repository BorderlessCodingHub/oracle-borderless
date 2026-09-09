"""Nó `navigate`: executa `navigate_platform` FORA do ToolNode para que o destino
entre no state (`navigation`) e saia no chunk `updates` antes da frase final
(spec §5.3). HTTP-only: roda na fase `stream()`, sem sessão de banco (ADR-0020).

Três invariantes:
- **uma navegação por turno** — a segunda chamada vira ToolMessage de erro e o
  destino já resolvido permanece;
- **erro nunca derruba o turno** — plataforma fora, token recusado ou destino
  inválido viram ToolMessage de erro e o modelo explica ao usuário;
- **o token só é lido de `configurable["platform_token"]`** e nunca é logado.
"""

import logging

from langchain_core.messages import AIMessage, ToolMessage

from src.support.agent.graph.state import TurnState
from src.support.agent.tools import NAVIGATE_TOOL_NAME, wrap_tool_content
from src.support.clients.borderless.borderless_navigation_client import (
    BorderlessNavigationClient,
    NavigationValidationError,
)

logger = logging.getLogger(__name__)


def _last_ai_message(state: TurnState) -> AIMessage | None:
    for message in reversed(state.get("messages") or []):
        if isinstance(message, AIMessage):
            return message
    return None


def _error(call, text: str) -> ToolMessage:
    return ToolMessage(
        content=wrap_tool_content(text),
        tool_call_id=call["id"],
        name=call["name"],
        status="error",
    )


async def navigate_node(state: TurnState, config) -> dict:
    """Responde a TODAS as tool calls da última AIMessage: a de navegação
    resolvendo o destino, as demais com erro — deixar uma tool call sem
    ToolMessage faria o provider recusar a próxima chamada."""
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
            result = await client.resolve(
                token, str(args.get("destination", "")), topic=args.get("topic"), goal=args.get("goal")
            )
        except NavigationValidationError as exc:
            out.append(_error(call, f"(destino inválido; use um destes ids: {', '.join(exc.valid_destinations)})"))
            continue
        except Exception:  # token recusado, plataforma fora, contrato quebrado
            logger.warning("navigate_platform falhou", exc_info=True)
            out.append(_error(call, "(falha ao resolver a navegação: plataforma indisponível)"))
            continue
        navigation = result.to_public()
        signals.navigation_access = result.access
        out.append(ToolMessage(
            content=wrap_tool_content(result.to_tool_text()),
            tool_call_id=call["id"],
            name=call["name"],
        ))

    return {"messages": out, "navigation": navigation}
