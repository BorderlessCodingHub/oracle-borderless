from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class TurnTrace:
    """O que aconteceu num turno do oráculo. Entity pura — sem SQLAlchemy.

    Colunas planas são o que a página agrega em SQL; `events` é a sequência
    ordenada que o detalhe do turno exibe. Ver spec, seção 3.
    """

    uuid: UUID
    conversation_id: UUID
    question: str
    outcome: str  # "answer" | "refusal" | "error"
    created_at: datetime
    message_id: UUID | None = None
    user_email: str | None = None
    history_messages: int = 0
    history_tokens_est: int = 0
    gate_retrieve: bool = False
    gate_search_query: str | None = None
    gate_degraded: bool = False
    gate_ms: int = 0
    retrieval_ran: bool = False
    retrieval_top_k: int = 0
    retrieval_kept: int = 0
    retrieval_best_distance: float | None = None
    retrieval_threshold: float = 0.0
    retrieval_ms: int | None = None
    first_token_ms: int | None = None
    engine_ms: int | None = None
    citations_count: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    events: list[dict] = field(default_factory=list)

    def is_refusal(self) -> bool:
        return self.outcome == "refusal"
