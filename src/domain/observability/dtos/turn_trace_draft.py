"""Acumulador do trace de um turno. Puro: só memória, sem I/O e sem banco.

Atravessa duas fronteiras de sessão (ver spec, seção 1): a Action preenche as
fases do request, o controller completa a fase do engine, e a background task
pós-stream converte para Entity e persiste.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from uuid6 import uuid7

from src.domain.observability.entities.turn_trace import TurnTrace

_JSON_SAFE = (str, int, float, bool, type(None))


def _safe(value):
    """JSONB aceita só primitivos; qualquer outra coisa vira str.

    Existe para honrar o invariante "trace nunca derruba um turno": um detail
    inesperado não pode estourar na serialização depois, longe da origem.
    """
    if isinstance(value, _JSON_SAFE):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


@dataclass
class TurnTraceDraft:
    question: str
    clock: Callable[[], float] = time.monotonic

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

    outcome: str = "answer"
    first_token_ms: int | None = None
    engine_ms: int | None = None
    citations_count: int = 0
    tool_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    message_id: UUID | None = None
    signals: object | None = None  # TurnSignals preenchido pelos nós do grafo

    events: list[dict] = field(default_factory=list)
    _t0: float = field(init=False, default=0.0, repr=False)

    def __post_init__(self) -> None:
        self._t0 = self.clock()

    def elapsed_ms(self) -> int:
        return int((self.clock() - self._t0) * 1000)

    def record(self, step: str, **detail) -> None:
        self.events.append(
            {"at_ms": self.elapsed_ms(), "step": step, "detail": {k: _safe(v) for k, v in detail.items()}}
        )

    def to_entity(self, conversation_id: UUID) -> TurnTrace:
        return TurnTrace(
            uuid=uuid7(),
            conversation_id=conversation_id,
            message_id=self.message_id,
            user_email=self.user_email,
            question=self.question,
            history_messages=self.history_messages,
            history_tokens_est=self.history_tokens_est,
            gate_retrieve=self.gate_retrieve,
            gate_search_query=self.gate_search_query,
            gate_degraded=self.gate_degraded,
            gate_ms=self.gate_ms,
            retrieval_ran=self.retrieval_ran,
            retrieval_top_k=self.retrieval_top_k,
            retrieval_kept=self.retrieval_kept,
            retrieval_best_distance=self.retrieval_best_distance,
            retrieval_threshold=self.retrieval_threshold,
            retrieval_ms=self.retrieval_ms,
            outcome=self.outcome,
            first_token_ms=self.first_token_ms,
            engine_ms=self.engine_ms,
            citations_count=self.citations_count,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            error=self.error,
            events=list(self.events),
            created_at=datetime.now(timezone.utc),
        )
