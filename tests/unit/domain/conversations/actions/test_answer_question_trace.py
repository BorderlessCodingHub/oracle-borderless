"""O que a Action registra no trace nas três rotas do turno.

Arquivo autocontido de propósito: os fakes do `test_answer_question_action.py`
vivem dentro dele (privados), então duplicar os mínimos aqui é mais barato e
menos arriscado que refatorar um teste verde para um conftest compartilhado.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from uuid6 import uuid7

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentStreamChunk, KnowledgeSnippet, RetrievalDecision

SNIPPET = KnowledgeSnippet(
    "trecho", Citation("notion", "Doc", "https://n.so/x", "trecho", "pid")
)


class FakeGate:
    def __init__(self, decision: RetrievalDecision) -> None:
        self.decision = decision

    async def decide(self, question, history):
        return self.decision


class FakeSearch:
    """Precisa de `.embeddings` porque o caminho de recusa embeda a query para
    medir a distância do vizinho mais próximo."""

    class _Embeddings:
        async def embed_query(self, query):
            return [0.0, 1.0]

    def __init__(self, snippets) -> None:
        self.snippets = snippets
        self.called_with = None
        self.embeddings = self._Embeddings()

    async def execute(self, query, top_k=None):
        self.called_with = query
        return self.snippets


class FakeEngine:
    async def stream_answer(self, question, history, knowledge, metrics=None):
        yield AgentStreamChunk(type="text", text="resposta")
        yield AgentStreamChunk(type="sources", citations=[])


class FakeSections:
    async def execute(self):
        return ["Mentorship", "Bootcamps"]


class FakeChunks:
    def __init__(self, nearest=None) -> None:
        self.nearest = nearest

    async def nearest_distance(self, embedding):
        return self.nearest


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


def _make_action(gate, search, chunks=None) -> AnswerQuestionAction:
    action = AnswerQuestionAction(
        engine=FakeEngine(),
        search=search,
        gate=gate,
        sections=FakeSections(),
        chunks=chunks or FakeChunks(),
    )
    action.conversations = FakeConvRepo()
    action.messages = FakeMsgRepo()
    return action


@pytest.mark.asyncio
async def test_retrieve_path_records_gate_and_retrieval():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="renovação de PSP")),
        search=FakeSearch([SNIPPET]),
    )

    _, _, draft = await action.execute("e as renovações?", None, None)

    assert draft.gate_retrieve is True
    assert draft.gate_search_query == "renovação de PSP"
    assert draft.retrieval_ran is True
    assert draft.retrieval_kept == 1
    assert draft.outcome == "answer"
    assert [e["step"] for e in draft.events] == ["turn_start", "recency", "gate", "retrieval"]


@pytest.mark.asyncio
async def test_skip_path_records_no_retrieval():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=False, search_query="")),
        search=FakeSearch([]),
    )

    _, _, draft = await action.execute("oi", None, None)

    assert draft.gate_retrieve is False
    assert draft.retrieval_ran is False
    assert draft.retrieval_kept == 0
    assert draft.outcome == "answer"
    assert "retrieval" not in [e["step"] for e in draft.events]


@pytest.mark.asyncio
async def test_refusal_path_records_outcome_and_nearest_distance():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="bolo de cenoura")),
        search=FakeSearch([]),  # nada passou do limiar
        chunks=FakeChunks(nearest=0.72),
    )

    _, _, draft = await action.execute("como faço bolo de cenoura?", None, None)

    assert draft.outcome == "refusal"
    assert draft.retrieval_ran is True
    assert draft.retrieval_kept == 0
    assert draft.retrieval_best_distance == 0.72
    assert [e["step"] for e in draft.events][-1] == "refusal"


@pytest.mark.asyncio
async def test_degraded_gate_with_empty_knowledge_does_not_refuse():
    """A guarda do fail-open: gate degradado nunca classificou o turno."""
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=True, search_query="oi", degraded=True)),
        search=FakeSearch([]),
    )

    _, _, draft = await action.execute("oi", None, None)

    assert draft.outcome == "answer"
    assert draft.gate_degraded is True


@pytest.mark.asyncio
async def test_history_tokens_are_estimated_from_the_loaded_recency():
    action = _make_action(
        gate=FakeGate(RetrievalDecision(retrieve=False, search_query="")),
        search=FakeSearch([]),
    )

    class _WithHistory(FakeMsgRepo):
        async def load_recent(self, conversation_id):
            from src.support.agent.ports import AgentMessage

            return [AgentMessage(role="user", content="a" * 400)]

    action.messages = _WithHistory()
    _, _, draft = await action.execute("oi", None, None)

    assert draft.history_messages == 1
    assert draft.history_tokens_est == 100  # 400 // 4
