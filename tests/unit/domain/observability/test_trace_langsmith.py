"""O trace guarda a referência ao run, não a sequência de eventos."""

from uuid import uuid4

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


def test_the_draft_carries_the_run_id_to_the_entity():
    draft = TurnTraceDraft(question="q")
    draft.langsmith_run_id = "run-123"

    entity = draft.to_entity(uuid4())

    assert entity.langsmith_run_id == "run-123"


def test_a_turn_without_tracing_has_no_run_id():
    entity = TurnTraceDraft(question="q").to_entity(uuid4())
    assert entity.langsmith_run_id is None


def test_the_draft_no_longer_records_events():
    draft = TurnTraceDraft(question="q")
    assert not hasattr(draft, "record"), "draft.record() deveria ter saído junto com events"
    assert not hasattr(draft, "events")
