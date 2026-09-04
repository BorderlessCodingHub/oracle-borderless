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
class TextChunk:
    """Texto do modelo de resposta (ou o texto canônico da recusa)."""

    text: str


@dataclass
class SourcesChunk:
    """Fontes do turno. Sempre o último chunk do stream."""

    citations: list[Citation] = field(default_factory=list)


@dataclass
class StepChunk:
    """Um nó do grafo abriu ou fechou: gate, retrieve, refuse ou answer.

    `detail` só vem no `finished` e só quando há dado útil para a UI
    (ex.: {"kept": 4} do retrieval). Ver ADR-0019.
    """

    name: str
    phase: Literal["started", "finished"]
    detail: dict | None = None


@dataclass
class ToolCallStartChunk:
    id: str
    name: str


@dataclass
class ToolCallArgsChunk:
    """Fragmento do JSON dos argumentos, como o provedor o entrega."""

    id: str
    delta: str


@dataclass
class ToolCallEndChunk:
    id: str


@dataclass
class ToolCallResultChunk:
    """Só o status. O conteúdo que a tool devolveu ao modelo NUNCA passa por
    aqui (regra 4 do CLAUDE.md) — fica no LangSmith."""

    id: str
    status: Literal["ok", "error"]


AgentStreamChunk = (
    TextChunk
    | SourcesChunk
    | StepChunk
    | ToolCallStartChunk
    | ToolCallArgsChunk
    | ToolCallEndChunk
    | ToolCallResultChunk
)


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

    # Latência do estágio de resposta, medida DENTRO do grafo (revisão I2).
    # Antes o controller cronometrava a partir do início do corpo SSE; com o
    # consumo em duas fases o primeiro token já nasce durante o `await start()`,
    # então aquele relógio dava `first_token_ms` ≈ 0 sempre e deixava de fora
    # justamente a fatia dominante do `engine_ms`. Quem mede agora é quem sabe:
    # o nó `answer` carimba a entrada, o runner fecha as duas contas.
    #
    # `answer_started_at` é interno (time.monotonic da PRIMEIRA entrada no nó
    # `answer`) e não vai para o trace — só serve de origem das duas medidas
    # abaixo. Também é o marcador que distingue "o estágio de resposta começou"
    # de "ainda estávamos em gate/retrieve/refuse" (ver runner, revisão I3).
    answer_started_at: float | None = None
    # Ambos ficam None no caminho de recusa: a recusa é texto canônico emitido
    # na hora, e entrar nas médias do motor misturaria as duas coisas.
    first_token_ms: int | None = None
    engine_ms: int | None = None


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
