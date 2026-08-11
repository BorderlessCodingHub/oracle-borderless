from dataclasses import dataclass, field


@dataclass
class TraceSummary:
    """Agregado dos `agent_traces` numa janela de tempo — o que o mapa de ops mostra."""

    turns: int = 0
    gate_retrieve: int = 0
    gate_skip: int = 0
    gate_degraded: int = 0
    answers: int = 0
    refusals: int = 0
    errors: int = 0
    avg_first_token_ms: float | None = None
    max_first_token_ms: int | None = None
    avg_engine_ms: float | None = None
    max_engine_ms: int | None = None
    avg_retrieval_kept: float | None = None
    avg_best_distance: float | None = None


@dataclass
class KnowledgeCounts:
    """Contagens da base de conhecimento para a página de ops."""

    documents_active: int = 0
    documents_archived: int = 0
    chunks: int = 0
    sections: list[str] = field(default_factory=list)


@dataclass
class SyncStatus:
    """Status do último run do job de sincronização da base."""

    job_name: str | None = None
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


@dataclass
class OpsOverview:
    """Tudo que a página de ops precisa numa chamada só."""

    window: str
    knowledge: KnowledgeCounts
    sync: SyncStatus
    traces: TraceSummary
    rag_top_k: int
    rag_max_distance: float
