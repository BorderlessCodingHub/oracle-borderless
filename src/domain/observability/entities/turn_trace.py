from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class TurnTrace:
    """O que aconteceu num turno do oráculo. Entity pura — sem SQLAlchemy.

    Colunas planas são o que a página agrega em SQL; `langsmith_run_id` é a
    referência ao run completo, cuja sequência passo-a-passo o LangSmith já
    mostra melhor do que o Postgres conseguiria. Ver spec, seção 3.
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
    langsmith_run_id: str | None = None
    intent: str | None = None
    navigation_called: bool = False
    navigation_access: str | None = None

    lesson_id: str | None = None
    program_slug: str | None = None
    lesson_coverage: str | None = None
    question_embedding: list[float] | None = None

    def is_refusal(self) -> bool:
        return self.outcome == "refusal"
