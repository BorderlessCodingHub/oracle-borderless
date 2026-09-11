"""Estado do turno que atravessa o grafo. Só dados — decisões ficam em edges.py."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, KnowledgeSnippet


class TurnState(TypedDict, total=False):
    # entrada
    question: str
    history: list[AgentMessage]
    # knowledge injetado de fora (eval adversarial) em vez de recuperado
    preset_knowledge: bool
    # a barra manda mode="navigate" (locale sempre presente); intent é preset
    # nesse modo — sem gate, sem RAG (spec §5.3). navigation fica None até a
    # Task 4 escrever a decisão de navegação.
    mode: str
    locale: str
    intent: str
    navigation: dict | None

    # tool loop — o reducer add_messages acumula as idas e voltas
    messages: Annotated[list[AnyMessage], add_messages]

    # gate
    retrieve: bool
    search_query: str
    degraded: bool

    # retrieval
    knowledge: list[KnowledgeSnippet]

    # saída
    answer: str
    citations: list[Citation]
    outcome: str  # "answer" | "refusal"
