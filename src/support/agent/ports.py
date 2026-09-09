"""Fronteira entre domínio e o grafo LangGraph (ADR-0016).

O domínio consome estes tipos; NÃO importa langgraph/langchain. Na direção
oposta, os nós do grafo consomem Actions de domínio pelos Protocols abaixo —
`support/` nunca importa `domain/`.
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Protocol

from src.domain.shared.value_objects.citation import Citation


@dataclass
class AgentMessage:
    role: str  # "user" | "assistant"
    content: str


ROOT_NAME = "LangGraph"
"""`name` que o LangGraph dá ao grafo raiz nos eventos do `astream_events`."""


@dataclass
class GraphEvent:
    """Um StreamEvent do `astream_events`, já REDIGIDO pelo runner (regra 4).

    Espelha `langchain_core.runnables.schema.StandardStreamEvent` campo a
    campo, sem importar langchain — o domínio consome isto. `data` carrega
    `Citation` onde há fontes; quem serializa é a camada `app` (ADR-0021).
    """

    event: str
    name: str
    run_id: str
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    parent_ids: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def node(self) -> str | None:
        return self.metadata.get("langgraph_node")

    @property
    def is_root(self) -> bool:
        return not self.parent_ids


def _updates_chunk(event: GraphEvent) -> dict | None:
    """O payload de um chunk `["updates", {...}]` do raiz, ou None."""
    if event.event != "on_chain_stream" or not event.is_root:
        return None
    chunk = event.data.get("chunk")
    if isinstance(chunk, (list, tuple)) and len(chunk) == 2 and chunk[0] == "updates":
        return chunk[1] or {}
    return None


def text_of(event: GraphEvent) -> str:
    """Texto que vira resposta: os tokens do `answer` (`on_chat_model_stream`) e
    o texto canônico da recusa (chave `answer` do update do nó `refuse`). ""
    para qualquer outro evento — inclusive o `on_chain_end` do `refuse`, que
    repete o texto e não pode ser contado duas vezes."""
    if event.event == "on_chat_model_stream" and event.node == "answer":
        chunk = event.data.get("chunk") or {}
        return chunk.get("content") or ""
    updates = _updates_chunk(event)
    if updates is not None:
        return (updates.get("refuse") or {}).get("answer") or ""
    return ""


def citations_of(event: GraphEvent) -> list[Citation] | None:
    """As fontes do turno: só no `on_chain_end` do raiz (state final). None nos
    demais eventos, [] quando o turno terminou sem fontes (recusa)."""
    if event.event == "on_chain_end" and event.is_root:
        output = event.data.get("output") or {}
        return list(output.get("citations") or [])
    return None


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
    # Classificação do gate: "knowledge" | "navigate" | "chit_chat". None até o
    # gate rodar (ou até o runner presetar "navigate" em mode == "navigate",
    # que pula o gate — ver TurnGraphRunner.run).
    intent: str | None = None

    retrieval_ran: bool = False
    retrieval_top_k: int = 0
    retrieval_kept: int = 0
    retrieval_ms: int | None = None
    retrieval_best_distance: float | None = None
    retrieval_threshold: float = 0.0

    outcome: str = "answer"  # "answer" | "refusal" | "error"

    # Latência do estágio de resposta, medida DENTRO do grafo (revisão I2).
    # O controller não pode cronometrá-la: o corpo SSE começa antes do grafo
    # rodar, então um relógio de fora mediria gate + retrieval junto. Quem mede
    # é quem sabe: o nó `answer` carimba a entrada, o runner fecha as duas contas.
    #
    # `answer_started_at` é interno (time.monotonic da PRIMEIRA entrada no nó
    # `answer`) e não vai para o trace — só serve de origem das duas medidas
    # abaixo.
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
    """Actions de domínio injetadas no grafo. Montadas por `RunTurnAction` DENTRO
    de um escopo de sessão (ADR-0020): repositórios leem a sessão do ContextVar
    em __init__ (regra 3), então isto não pode nascer em tempo de import nem no
    request — o request já fechou a sessão quando o corpo SSE começa."""

    search: KnowledgeSearchPort
    sections: KnowledgeSectionsPort
    refusal: Callable[[list[str], str], str]
    nearest: NearestDistancePort | None = None


class TurnRun(Protocol):
    """Um turno já montado, consumido em DUAS FASES (ADR-0020). Nada executa até
    `prelude()` ser iterado. Ambas as fases emitem `GraphEvent` já redigidos
    (ADR-0021)."""

    def prelude(self) -> AsyncIterator[GraphEvent]:
        """Fase 1: gate → retrieve → (refuse | entrada do answer). Toca o banco
        via `deps`: consumir ATÉ O FIM dentro de um escopo de sessão, antes de
        `stream()`. Termina depois de emitir o `on_chain_start` do nó `answer`
        ou o `on_chain_end` do nó `refuse`."""

    def stream(self) -> AsyncIterator[GraphEvent]:
        """Fase 2: o restante — tokens (`on_chat_model_stream`), tools, chunks
        de `updates`/`values`, `on_chain_end` do `answer` e, por último, o
        `on_chain_end` do raiz (com `citations`). Não toca o banco; deve rodar
        FORA de escopo de sessão. Chamar antes de `prelude()` esgotar é erro de
        programação (RuntimeError)."""

    async def aclose(self) -> None:
        """Encerra o turno antes do fim (desconexão, falha): cancela a execução
        do grafo. Idempotente; seguro chamar depois de `stream()` esgotar."""


class TurnGraphPort(Protocol):
    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        mode: str = "chat",
        locale: str = "pt-BR",
        extra_config: dict | None = None,
    ) -> TurnRun:
        """Monta o turno. Síncrono: só constrói o gerador do grafo e o emitter.

        `knowledge` pré-semeado pula gate e retrieval e vai direto ao nó de
        resposta; é o que o eval usa nos casos adversariais.

        `mode`/`locale` vêm do input do cliente (a barra manda "navigate", o
        chat manda "chat") e entram no state inicial do grafo.

        `extra_config` injeta entradas no `configurable` do grafo — existe para
        os testes passarem modelos fakes sem monkeypatch.
        """
        ...
