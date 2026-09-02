"""As recusas rankeadas por quão perto ficaram do limiar: o que falta na base."""

import pytest

from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


@pytest.mark.asyncio
async def test_gaps_rank_the_near_misses_first(seed_traces):
    """Uma recusa a 0.56 (limiar 0.55) é quase-cobertura; a 0.95 é fora de assunto."""
    await seed_traces([
        {"question": "como renovo o PSP?", "outcome": "refusal", "retrieval_best_distance": 0.56},
        {"question": "qual a capital da Mongólia?", "outcome": "refusal", "retrieval_best_distance": 0.95},
        {"question": "o que é o programa X?", "outcome": "refusal", "retrieval_best_distance": 0.60},
    ])

    gaps = await TurnTraceRepository().knowledge_gaps("24h", limit=10)

    assert [g.question for g in gaps][:2] == ["como renovo o PSP?", "o que é o programa X?"]


@pytest.mark.asyncio
async def test_answered_turns_are_not_gaps(seed_traces):
    await seed_traces([
        {"question": "o que é PSP?", "outcome": "answer", "retrieval_best_distance": 0.30},
    ])
    assert await TurnTraceRepository().knowledge_gaps("24h") == []


@pytest.mark.asyncio
async def test_refusals_without_a_measured_distance_are_skipped(seed_traces):
    """Sem distância não dá para dizer se foi quase-cobertura ou fora de assunto."""
    await seed_traces([
        {"question": "q", "outcome": "refusal", "retrieval_best_distance": None},
    ])
    assert await TurnTraceRepository().knowledge_gaps("24h") == []


@pytest.mark.asyncio
async def test_the_same_question_asked_twice_counts_as_one_gap(seed_traces):
    await seed_traces([
        {"question": "como renovo o PSP?", "outcome": "refusal", "retrieval_best_distance": 0.56},
        {"question": "como renovo o PSP?", "outcome": "refusal", "retrieval_best_distance": 0.58},
    ])

    gaps = await TurnTraceRepository().knowledge_gaps("24h")

    assert len(gaps) == 1
    assert gaps[0].occurrences == 2
    assert gaps[0].best_distance == pytest.approx(0.56)
