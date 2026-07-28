"""Fronteira fina entre domínio e o motor Pydantic AI (ver ADR-0007).

O domínio (AnswerQuestionAction) consome estes tipos; NÃO importa pydantic_ai.
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol

from src.domain.shared.value_objects.citation import Citation


@dataclass
class AgentMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class AgentStreamChunk:
    type: Literal["text", "sources"]
    text: str = ""
    citations: list[Citation] = field(default_factory=list)


@dataclass
class KnowledgeSnippet:
    """Trecho recuperado da base (RAG clássico), com sua fonte para citação."""

    content: str
    citation: Citation


@dataclass
class RetrievalDecision:
    """Decisão do retrieval gate: recuperar ou não, e a query já resolvida."""

    retrieve: bool
    search_query: str  # standalone, context-resolved; "" quando retrieve é False
    # True só no caminho de exceção do gate (erro/timeout): o gate NÃO chegou a
    # classificar o turno, então `retrieve=True` aqui é um chute de segurança
    # (fail-open), não uma classificação real. Uma recusa fundamentada exige
    # ter classificado o turno como substantivo — sem isso, refusal seria
    # injustificada (ex.: "oi" durante um timeout do gate).
    degraded: bool = False


class RetrievalGatePort(Protocol):
    async def decide(
        self, question: str, history: list[AgentMessage]
    ) -> RetrievalDecision: ...


class OracleEnginePort(Protocol):
    def stream_answer(
        self,
        question: str,
        history: list[AgentMessage],
        knowledge: list[KnowledgeSnippet],
    ) -> AsyncIterator[AgentStreamChunk]: ...
