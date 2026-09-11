"""Montagem do grafo do turno. Sem checkpointer de propósito: o histórico da
conversa vive em `conversations`/`messages`, e duplicá-lo aqui criaria duas
fontes da verdade (ADR-0016)."""

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.support.agent.graph.edges import after_answer, has_grounding, route_entry, should_retrieve
from src.support.agent.graph.navigate_node import navigate_node
from src.support.agent.graph.nodes import answer_node, gate_node, refuse_node, retrieve_node
from src.support.agent.graph.state import TurnState
from src.support.agent.tools import tool_node_tools


def build_turn_graph():
    builder = StateGraph(TurnState)

    builder.add_node("gate", gate_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("refuse", refuse_node)
    builder.add_node("answer", answer_node)
    # navigate_platform fica FORA do ToolNode: quem a executa é o nó `navigate`,
    # que escreve o destino no state para ele sair no fio antes da frase final.
    builder.add_node("tools", ToolNode(tool_node_tools()))
    builder.add_node("navigate", navigate_node)

    # Entrada condicional: knowledge pré-semeado (eval adversarial) pula o gate.
    builder.add_conditional_edges(START, route_entry, {"gate": "gate", "answer": "answer"})
    builder.add_conditional_edges("gate", should_retrieve, {"retrieve": "retrieve", "answer": "answer"})
    builder.add_conditional_edges("retrieve", has_grounding, {"refuse": "refuse", "answer": "answer"})
    builder.add_conditional_edges("answer", after_answer, {"navigate": "navigate", "tools": "tools", END: END})
    builder.add_edge("tools", "answer")
    builder.add_edge("navigate", "answer")
    builder.add_edge("refuse", END)

    return builder.compile()


TURN_GRAPH = build_turn_graph()
