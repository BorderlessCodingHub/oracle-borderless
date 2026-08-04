from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from uuid6 import uuid7

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.repositories.conversation_repository import (
    ConversationRepository,
)
from src.domain.observability.entities.turn_trace import TurnTrace
from src.domain.observability.repositories.turn_trace_repository import TurnTraceRepository


async def _conversation() -> Conversation:
    now = datetime.now(timezone.utc)
    return await ConversationRepository().create(
        Conversation(uuid=uuid7(), user_email=None, title="t", created_at=now, updated_at=now, deleted_at=None)
    )


def _trace(conversation_id, **overrides) -> TurnTrace:
    base = dict(
        uuid=uuid7(),
        conversation_id=conversation_id,
        question="q",
        outcome="answer",
        created_at=datetime.now(timezone.utc),
        gate_retrieve=True,
        retrieval_ran=True,
        retrieval_kept=2,
        retrieval_best_distance=0.4,
        retrieval_threshold=0.55,
        engine_ms=1000,
        first_token_ms=200,
    )
    base.update(overrides)
    return TurnTrace(**base)


@pytest.mark.asyncio
async def test_summarize_counts_gate_split_and_outcomes(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    await repo.append(_trace(conversation.uuid))
    await repo.append(_trace(conversation.uuid, gate_retrieve=False, retrieval_ran=False))
    await repo.append(_trace(conversation.uuid, outcome="refusal", retrieval_kept=0))
    await repo.append(_trace(conversation.uuid, outcome="error", engine_ms=None))
    await db_session.flush()

    summary = await repo.summarize(window="all")

    assert summary.turns == 4
    assert summary.gate_retrieve == 3
    assert summary.gate_skip == 1
    assert summary.answers == 2
    assert summary.refusals == 1
    assert summary.errors == 1
    assert summary.avg_engine_ms == pytest.approx(1000, abs=1)


@pytest.mark.asyncio
async def test_summarize_respects_the_window(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    old = _trace(conversation.uuid)
    await repo.append(old)
    fresh = await repo.append(_trace(conversation.uuid))
    await db_session.flush()
    # empurra só a linha `old` para 10 dias atrás — `fresh` fica com created_at
    # do server_default (agora), provando que uma linha recente é incluída,
    # não só que uma linha velha é excluída.
    from sqlalchemy import update

    from src.domain.observability.models.turn_trace import TurnTraceModel

    await db_session.execute(
        update(TurnTraceModel)
        .where(TurnTraceModel.uuid == old.uuid)
        .values(created_at=datetime.now(timezone.utc) - timedelta(days=10))
    )
    await db_session.flush()

    assert (await repo.summarize(window="all")).turns == 2
    assert (await repo.summarize(window="7d")).turns == 1
    assert (await repo.summarize(window="24h")).turns == 1
    assert [t.uuid for t in await repo.list_recent(window="7d", limit=10)] == [fresh.uuid]


@pytest.mark.asyncio
async def test_list_recent_is_newest_first_and_respects_limit(db_session):
    conversation = await _conversation()
    repo = TurnTraceRepository()
    for n in range(3):
        await repo.append(_trace(conversation.uuid, question=f"q{n}"))
    await db_session.flush()

    recent = await repo.list_recent(window="all", limit=2)
    assert len(recent) == 2


@pytest.mark.asyncio
async def test_summarize_on_empty_window_returns_zeros(db_session):
    summary = await TurnTraceRepository().summarize(window="24h")
    assert summary.turns == 0
    assert summary.avg_engine_ms is None


@pytest.mark.asyncio
async def test_summarize_with_only_refusals_averages_are_none(db_session):
    """Recusa determinística não roda motor: engine_ms/first_token_ms ficam
    NULL (Task 5). Uma janela só com recusas não pode estourar a média."""
    conversation = await _conversation()
    repo = TurnTraceRepository()
    await repo.append(
        _trace(conversation.uuid, outcome="refusal", retrieval_kept=0, engine_ms=None, first_token_ms=None)
    )
    await repo.append(
        _trace(conversation.uuid, outcome="refusal", retrieval_kept=0, engine_ms=None, first_token_ms=None)
    )
    await db_session.flush()

    summary = await repo.summarize(window="all")

    assert summary.turns == 2
    assert summary.refusals == 2
    assert summary.avg_engine_ms is None
    assert summary.avg_first_token_ms is None
    assert summary.max_engine_ms is None


@pytest.mark.asyncio
async def test_summarize_raises_on_invalid_window(db_session):
    with pytest.raises(ValueError, match="janela inválida"):
        await TurnTraceRepository().summarize(window="30d")
