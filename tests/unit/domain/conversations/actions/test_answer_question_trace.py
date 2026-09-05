"""O que a Action ainda registra no trace, depois que gate/retrieval/recusa
viraram nós do grafo.

O que este arquivo cobria sobre gate, retrieval e recusa (draft.gate_retrieve,
draft.retrieval_ran, draft.outcome == "refusal", etc.) é responsabilidade dos
nós agora — coberto em `tests/unit/support/agent/graph/test_nodes.py` e
`test_edges.py`. A Action só grava `history_messages`/`history_tokens_est`
(cálculo local) e entrega o MESMO objeto `signals` ao grafo e ao draft — o
resto (`gate_retrieve`, `retrieval_kept`, `outcome`, ...) só chega à coluna do
trace via `_absorb_engine_metrics` no controller, testado em
`tests/integration/api/test_ask_trace_persistence.py`.
"""

from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from tests.fakes.fake_turn_graph import FakeTurnGraph


class FakeSearch:
    async def execute(self, query, top_k=None):
        return []


class FakeSections:
    async def execute(self):
        return ["Mentorship", "Bootcamps"]


class FakeConvRepo:
    async def get_by_id(self, cid):
        return None

    async def create(self, conversation):
        return conversation


class FakeMsgRepo:
    def __init__(self) -> None:
        self.appended = []

    async def append(self, message):
        self.appended.append(message)
        return message

    async def load_recent(self, conversation_id):
        return []


def _make_action(graph=None) -> AnswerQuestionAction:
    action = AnswerQuestionAction(
        graph=graph or FakeTurnGraph(), search=FakeSearch(), sections=FakeSections()
    )
    action.conversations = FakeConvRepo()
    action.messages = FakeMsgRepo()
    return action


@pytest.mark.asyncio
async def test_history_tokens_are_estimated_from_the_loaded_recency():
    action = _make_action()

    class _WithHistory(FakeMsgRepo):
        async def load_recent(self, conversation_id):
            from src.support.agent.ports import AgentMessage

            return [AgentMessage(role="user", content="a" * 400)]

    action.messages = _WithHistory()
    _, stream, draft = await action.execute("oi", uuid4(), None)
    [c async for c in stream]

    assert draft.history_messages == 1
    assert draft.history_tokens_est == 100  # 400 // 4


@pytest.mark.asyncio
async def test_signals_is_assigned_to_the_draft_before_the_graph_runs():
    """A Action instancia `TurnSignals`, grava em `draft.signals` e passa o
    MESMO objeto ao grafo — é o que permite ao controller ler de volta o que os
    nós escreveram (`_absorb_engine_metrics`)."""
    action = _make_action(graph=FakeTurnGraph(outcome="refusal", retrieve=True, retrieval_kept=0))

    _, stream, draft = await action.execute("como faço bolo de cenoura?", uuid4(), None)
    [c async for c in stream]

    assert draft.signals is not None
    assert draft.signals.outcome == "refusal"
    assert draft.signals.retrieval_kept == 0
