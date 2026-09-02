"""Fronteira entre domínio e o grafo LangGraph (ADR-0016).

O domínio consome estes tipos; NÃO importa langgraph/langchain. Na direção
oposta, os nós do grafo consomem Actions de domínio pelos Protocols abaixo —
`support/` nunca importa `domain/`.
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Literal, Protocol

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
    """Decisão do gate: recuperar ou não, e a query já resolvida."""

    retrieve: bool
    search_query: str  # standalone, context-resolved; "" quando retrieve é False
    # True só no caminho de exceção do gate (erro/timeout): o gate NÃO chegou a
    # classificar o turno, então `retrieve=True` aqui é um chute de segurança
    # (fail-open), não uma classificação real. Uma recusa fundamentada exige ter
    # classificado o turno como substantivo — sem isso, refusal seria
    # injustificada (ex.: "oi" durante um timeout do gate).
    degraded: bool = False


@dataclass
class TurnSignals:
    """Sinal do turno, escrito pelos nós do grafo conforme ele progride.

    Sucede o antigo `TurnMetrics`, absorvendo o que a Action media à mão e o que
    o extinto `draft.record()` gravava como JSON — a sequência passo-a-passo
    agora vive no LangSmith, não no Postgres. Mesmo padrão de sempre: objeto
    mutável instanciado pela Action, escrito por quem executa.
    """

    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    gate_retrieve: bool = False
    gate_search_query: str | None = None
    gate_degraded: bool = False
    gate_ms: int = 0

    retrieval_ran: bool = False
    retrieval_top_k: int = 0
    retrieval_kept: int = 0
    retrieval_ms: int | None = None
    retrieval_best_distance: float | None = None
    retrieval_threshold: float = 0.0

    outcome: str = "answer"  # "answer" | "refusal" | "error"


class KnowledgeSearchPort(Protocol):
    """Satisfeito por SearchKnowledgeBaseAction, sem alteração."""

    async def execute(self, query: str, top_k: int | None = None) -> list[KnowledgeSnippet]: ...


class KnowledgeSectionsPort(Protocol):
    """Satisfeito por ListKnowledgeSectionsAction, sem alteração."""

    async def execute(self) -> list[str]: ...


class NearestDistancePort(Protocol):
    """Distância do vizinho mais próximo, só para o trace da recusa."""

    async def execute(self, query: str) -> float | None: ...


@dataclass
class TurnDependencies:
    """Actions de domínio injetadas no grafo. Montadas pela Action DENTRO do
    request: repositórios leem a sessão do ContextVar em __init__ (regra 3), então
    isto não pode nascer em tempo de import."""

    search: KnowledgeSearchPort
    sections: KnowledgeSectionsPort
    refusal: Callable[[list[str], str], str]
    nearest: NearestDistancePort | None = None


class TurnGraphPort(Protocol):
    async def start(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
        """Dirige o grafo até o PRIMEIRO token e devolve o gerador do restante.

        O await desta chamada executa gate e retrieval — precisa acontecer dentro
        do escopo da sessão de banco. Ver spec, seção 5.

        `knowledge` pré-semeado pula gate e retrieval e vai direto ao nó de
        resposta; é o que o eval usa nos casos adversariais.

        `extra_config` injeta entradas no `configurable` do grafo — existe para
        os testes passarem modelos fakes sem monkeypatch.
        """
        ...
