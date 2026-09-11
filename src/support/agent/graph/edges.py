"""As decisões do turno. Funções puras: recebem estado, devolvem o nome do
próximo nó. As três primeiras são tradução 1:1 do if/else que vivia em
AnswerQuestionAction; `after_answer` substitui o `tools_condition` do prebuilt
para poder desviar a navegação ao nó próprio."""

from typing import Literal

from langgraph.graph import END

from src.support.agent.graph.state import TurnState
from src.support.agent.tools import NAVIGATE_TOOL_NAME


def route_entry(state: TurnState) -> Literal["answer", "gate"]:
    """Knowledge pré-semeado pula gate e retrieval; `mode == "navigate"` também
    pula o gate — a barra já fixou a intenção (spec §5.3).

    Existe para o harness de eval: nos casos `adversarial` o contexto envenenado
    é injetado à mão, e fazer o gate classificá-lo mediria a coisa errada.
    """
    if state.get("preset_knowledge") or state.get("mode") == "navigate":
        return "answer"
    return "gate"


def should_retrieve(state: TurnState) -> Literal["retrieve", "answer"]:
    """navigate e chit_chat nunca retrievam, mesmo que `retrieve` tenha vindo
    True — o intent classificado pelo gate tem prioridade. Sem `intent` no
    state (compat), assume knowledge."""
    intent = state.get("intent", "knowledge")
    return "retrieve" if state.get("retrieve") and intent == "knowledge" else "answer"


def has_grounding(state: TurnState) -> Literal["refuse", "answer"]:
    """Recusa só quando o gate PEDIU busca de verdade e nada passou do limiar.

    Um gate `degraded` (erro/timeout) nunca classificou o turno: o retrieve=True
    dali é o chute de segurança do fail-open, não uma decisão fundamentada.
    Recusar nesse caso seria injustificado (ex.: "oi" durante um timeout).
    """
    if state.get("knowledge"):
        return "answer"
    return "answer" if state.get("degraded") else "refuse"


def after_answer(state: TurnState) -> Literal["navigate", "tools", "__end__"]:
    """Sucede `tools_condition`: sem tool call o turno acaba; uma chamada a
    `navigate_platform` vai ao nó `navigate` (que também responde às outras tool
    calls da mesma mensagem); o resto vai ao ToolNode."""
    message = state["messages"][-1] if state.get("messages") else None
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return END
    if any(call["name"] == NAVIGATE_TOOL_NAME for call in calls):
        return "navigate"
    return "tools"
