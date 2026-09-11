"""O grafo montado: topologia e caminhos completos com modelos fakes."""

import pytest

from src.support.agent.graph.builder import build_turn_graph


def test_the_graph_has_every_node_of_the_turn():
    graph = build_turn_graph()
    nodes = set(graph.get_graph().nodes)
    for expected in ("gate", "retrieve", "refuse", "answer", "tools", "navigate"):
        assert expected in nodes, f"nó ausente: {expected}"


def test_the_graph_compiles_without_a_checkpointer():
    """Decisão da spec: histórico vem dos repositórios, não do LangGraph."""
    graph = build_turn_graph()
    assert graph.checkpointer is None
