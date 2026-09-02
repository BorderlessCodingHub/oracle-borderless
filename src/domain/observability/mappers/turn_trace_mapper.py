from datetime import datetime

from src.domain.observability.entities.turn_trace import TurnTrace

_FLAT_FIELDS = (
    "uuid",
    "conversation_id",
    "message_id",
    "user_email",
    "question",
    "history_messages",
    "history_tokens_est",
    "gate_retrieve",
    "gate_search_query",
    "gate_degraded",
    "gate_ms",
    "retrieval_ran",
    "retrieval_top_k",
    "retrieval_kept",
    "retrieval_best_distance",
    "retrieval_threshold",
    "retrieval_ms",
    "outcome",
    "first_token_ms",
    "engine_ms",
    "citations_count",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "error",
    "langsmith_run_id",
)


class TurnTraceMapper:
    @staticmethod
    def to_model_attrs(entity: TurnTrace) -> dict:
        """`created_at` fica fora: é server_default do Postgres."""
        return {name: getattr(entity, name) for name in _FLAT_FIELDS}

    @staticmethod
    def to_entity(model) -> TurnTrace:
        attrs = {name: getattr(model, name) for name in _FLAT_FIELDS}
        return TurnTrace(created_at=model.created_at, **attrs)

    @staticmethod
    def to_entity_from_attrs(attrs: dict, created_at: datetime) -> TurnTrace:
        """Atalho de teste: monta a Entity a partir do dict do to_model_attrs."""
        return TurnTrace(created_at=created_at, **attrs)
