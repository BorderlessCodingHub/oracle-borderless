"""Montagem do grafo do turno. Sem checkpointer de propósito: o histórico da
conversa vive em `conversations`/`messages`, e duplicá-lo aqui criaria duas
fontes da verdade (ADR-0016)."""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.support.agent.graph.edges import has_grounding, route_entry, should_retrieve
from src.support.agent.graph.nodes import answer_node, gate_node, refuse_node, retrieve_node
from src.support.agent.graph.state import TurnState
from src.support.agent.tools import build_tools


def build_turn_graph():
    builder = StateGraph(TurnState)

    builder.add_node("gate", gate_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("refuse", refuse_node)
    builder.add_node("answer", answer_node)
    builder.add_node("tools", ToolNode(build_tools()))

    # Entrada condicional: knowledge pré-semeado (eval adversarial) pula o gate.
    builder.add_conditional_edges(START, route_entry, {"gate": "gate", "answer": "answer"})
    builder.add_conditional_edges("gate", should_retrieve, {"retrieve": "retrieve", "answer": "answer"})
    builder.add_conditional_edges("retrieve", has_grounding, {"refuse": "refuse", "answer": "answer"})
    builder.add_conditional_edges("answer", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "answer")
    builder.add_edge("refuse", END)

    return builder.compile()


TURN_GRAPH = build_turn_graph()
