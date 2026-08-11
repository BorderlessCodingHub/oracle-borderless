from uuid import uuid4

import pytest

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


class FakeClock:
    """Relógio determinístico: cada leitura avança 0,1s."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        value = self.t
        self.t += 0.1
        return value


def test_records_steps_in_order_with_monotonic_at_ms():
    draft = TurnTraceDraft(question="o que é o PSP?", clock=FakeClock())
    draft.record("gate", retrieve=True)
    draft.record("retrieval", kept=2)

    steps = [e["step"] for e in draft.events]
    at_ms = [e["at_ms"] for e in draft.events]

    assert steps == ["gate", "retrieval"]
    assert at_ms == sorted(at_ms)
    assert draft.events[0]["detail"] == {"retrieve": True}


def test_elapsed_ms_counts_from_construction():
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    # construção lê t=0.0; a próxima leitura devolve 0.1s → 100ms
    assert draft.elapsed_ms() == 100


def test_to_entity_carries_flat_fields_and_events():
    draft = TurnTraceDraft(question="o que é o PSP?", clock=FakeClock())
    draft.gate_retrieve = True
    draft.gate_search_query = "PSP"
    draft.retrieval_kept = 2
    draft.outcome = "answer"
    draft.record("turn_end", outcome="answer")

    conversation_id = uuid4()
    entity = draft.to_entity(conversation_id=conversation_id)

    assert entity.conversation_id == conversation_id
    assert entity.question == "o que é o PSP?"
    assert entity.gate_retrieve is True
    assert entity.gate_search_query == "PSP"
    assert entity.retrieval_kept == 2
    assert entity.outcome == "answer"
    assert entity.events[-1]["step"] == "turn_end"
    assert entity.uuid is not None


def test_record_never_raises_on_unserializable_detail():
    """O trace não pode derrubar um turno: detail estranho é coagido para str."""
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    draft.record("weird", obj=object())
    assert isinstance(draft.events[0]["detail"]["obj"], str)


def test_question_is_truncated_for_the_event_but_not_for_the_column():
    long_question = "a" * 5000
    draft = TurnTraceDraft(question=long_question, clock=FakeClock())
    draft.record("turn_start", question_chars=len(long_question))
    assert draft.question == long_question
    assert draft.events[0]["detail"]["question_chars"] == 5000


@pytest.mark.parametrize("outcome", ["answer", "refusal", "error"])
def test_outcome_accepts_only_the_three_known_values(outcome):
    draft = TurnTraceDraft(question="x", clock=FakeClock())
    draft.outcome = outcome
    assert draft.to_entity(conversation_id=uuid4()).outcome == outcome
