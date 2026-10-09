"""`apply_mentor_signals` é a lógica pura que preenche o draft do trace a
partir do `configurable` do turno mentor (Task 5) — extraída do call site do
controller para poder ser testada sem sessão/HTTP. Espelha o snippet do
brief que hoje vive sob o `try/except` de `_persist_turn`."""

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.domain.observability.services.mentor_trace import apply_mentor_signals
from src.support.core.settings import settings


def _draft() -> TurnTraceDraft:
    return TurnTraceDraft(question="quando usar PSP?")


def test_distances_feed_best_kept_ran_and_coverage():
    draft = _draft()
    cfg = {
        "lesson_distances": [0.42, 0.63],
        "question_embedding": [0.1, 0.2],
        "lesson_platform_video_id": "video-123",
        "lesson_program_slug": "base",
    }

    apply_mentor_signals(draft, cfg)

    assert draft.retrieval_best_distance == 0.42
    assert draft.retrieval_kept == 2
    assert draft.retrieval_ran is True
    assert draft.lesson_coverage == "partial"
    assert draft.intent == "mentor"
    assert draft.lesson_id == "video-123"
    assert draft.program_slug == "base"
    assert draft.question_embedding == [0.1, 0.2]
    # M2: top_k é o de verdade do mentor; sem limiar de propósito (busca de
    # aula não corta por distância — spec §4).
    assert draft.retrieval_top_k == settings.MENTOR_TOP_K
    assert draft.retrieval_threshold == 0.0


def test_empty_distances_mean_no_retrieval_and_a_content_gap():
    draft = _draft()
    cfg = {
        "lesson_distances": [],
        "question_embedding": [],
        "lesson_platform_video_id": "video-123",
        "lesson_program_slug": "base",
    }

    apply_mentor_signals(draft, cfg)

    assert draft.retrieval_ran is False
    assert draft.retrieval_kept == 0
    assert draft.retrieval_best_distance is None
    assert draft.lesson_coverage == "gap"


def test_empty_embedding_list_becomes_none_not_an_empty_list():
    draft = _draft()
    cfg = {
        "lesson_distances": [0.1],
        "question_embedding": [],
        "lesson_platform_video_id": "video-123",
        "lesson_program_slug": "base",
    }

    apply_mentor_signals(draft, cfg)

    assert draft.question_embedding is None


def test_missing_keys_never_raise():
    draft = _draft()

    apply_mentor_signals(draft, {})

    assert draft.retrieval_ran is False
    assert draft.retrieval_kept == 0
    assert draft.retrieval_best_distance is None
    assert draft.lesson_coverage == "gap"
    assert draft.intent == "mentor"
    assert draft.lesson_id is None
    assert draft.program_slug is None
    assert draft.question_embedding is None
    assert draft.retrieval_top_k == settings.MENTOR_TOP_K
    assert draft.retrieval_threshold == 0.0
