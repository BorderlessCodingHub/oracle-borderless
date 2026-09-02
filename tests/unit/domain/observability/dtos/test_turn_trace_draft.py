from uuid import uuid4

import pytest

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


def test_to_entity_carries_flat_fields_and_run_id():
    draft = TurnTraceDraft(question="o que é o PSP?")
    draft.gate_retrieve = True
    draft.gate_search_query = "PSP"
    draft.retrieval_kept = 2
    draft.outcome = "answer"
    draft.langsmith_run_id = "run-abc"

    conversation_id = uuid4()
    entity = draft.to_entity(conversation_id=conversation_id)

    assert entity.conversation_id == conversation_id
    assert entity.question == "o que é o PSP?"
    assert entity.gate_retrieve is True
    assert entity.gate_search_query == "PSP"
    assert entity.retrieval_kept == 2
    assert entity.outcome == "answer"
    assert entity.langsmith_run_id == "run-abc"
    assert entity.uuid is not None


def test_question_is_not_truncated_for_the_column():
    long_question = "a" * 5000
    draft = TurnTraceDraft(question=long_question)
    assert draft.question == long_question


@pytest.mark.parametrize("outcome", ["answer", "refusal", "error"])
def test_outcome_accepts_only_the_three_known_values(outcome):
    draft = TurnTraceDraft(question="x")
    draft.outcome = outcome
    assert draft.to_entity(conversation_id=uuid4()).outcome == outcome
