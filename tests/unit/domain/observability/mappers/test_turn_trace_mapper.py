from datetime import datetime, timezone
from uuid import uuid4

from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.mappers.turn_trace_mapper import TurnTraceMapper


def _entity(**overrides) -> TurnTrace:
    base = dict(
        uuid=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        user_email="alguem@exemplo.com",
        question="o que é o PSP?",
        history_messages=4,
        history_tokens_est=830,
        gate_retrieve=True,
        gate_search_query="renovação de PSP",
        gate_degraded=False,
        gate_ms=120,
        retrieval_ran=True,
        retrieval_top_k=6,
        retrieval_kept=2,
        retrieval_best_distance=0.427,
        retrieval_threshold=0.55,
        retrieval_ms=40,
        outcome="answer",
        first_token_ms=410,
        engine_ms=1980,
        citations_count=2,
        tool_calls=0,
        input_tokens=1200,
        output_tokens=300,
        error=None,
        langsmith_run_id="run-abc",
        intent="navigate",
        navigation_called=True,
        navigation_access="allowed",
        lesson_id=None,
        program_slug=None,
        lesson_coverage=None,
        question_embedding=None,
        created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TurnTrace(**base)


def test_to_model_attrs_carries_every_flat_field():
    entity = _entity()
    attrs = TurnTraceMapper.to_model_attrs(entity)

    assert attrs["uuid"] == entity.uuid
    assert attrs["conversation_id"] == entity.conversation_id
    assert attrs["gate_search_query"] == "renovação de PSP"
    assert attrs["retrieval_best_distance"] == 0.427
    assert attrs["outcome"] == "answer"
    assert attrs["langsmith_run_id"] == "run-abc"
    assert attrs["intent"] == "navigate"
    assert attrs["navigation_called"] is True
    assert attrs["navigation_access"] == "allowed"
    # created_at é server_default — o mapper não o envia
    assert "created_at" not in attrs


def test_roundtrip_through_a_stub_model():
    entity = _entity()
    attrs = TurnTraceMapper.to_model_attrs(entity)

    class StubModel:
        pass

    model = StubModel()
    for key, value in attrs.items():
        setattr(model, key, value)
    model.created_at = entity.created_at

    back = TurnTraceMapper.to_entity(model)
    assert back == entity


def test_optional_fields_survive_as_none():
    entity = _entity(
        message_id=None,
        user_email=None,
        gate_search_query=None,
        retrieval_best_distance=None,
        retrieval_ms=None,
        first_token_ms=None,
        engine_ms=None,
        input_tokens=None,
        output_tokens=None,
        error="timeout do modelo",
        outcome="error",
        intent=None,
        navigation_called=False,
        navigation_access=None,
    )
    back = TurnTraceMapper.to_entity_from_attrs(
        TurnTraceMapper.to_model_attrs(entity), created_at=entity.created_at
    )
    assert back == entity


def test_mentor_fields_roundtrip_both_directions():
    """Os quatro campos do Task 5 (lesson_id, program_slug, lesson_coverage,
    question_embedding) precisam sobreviver às duas direções do mapper — é o
    que evita a perda silenciosa de dado quando um campo novo esquece uma das
    quatro camadas."""
    entity = _entity(
        lesson_id="video-123",
        program_slug="base",
        lesson_coverage="partial",
        question_embedding=[0.1, 0.2, 0.3],
    )

    attrs = TurnTraceMapper.to_model_attrs(entity)
    assert attrs["lesson_id"] == "video-123"
    assert attrs["program_slug"] == "base"
    assert attrs["lesson_coverage"] == "partial"
    assert attrs["question_embedding"] == [0.1, 0.2, 0.3]

    class StubModel:
        pass

    model = StubModel()
    for key, value in attrs.items():
        setattr(model, key, value)
    model.created_at = entity.created_at

    back = TurnTraceMapper.to_entity(model)
    assert back == entity
