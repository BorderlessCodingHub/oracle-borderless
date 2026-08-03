"""Recusa quando a base não cobre — e a guarda que evita recusar saudação."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from tests.fakes.fake_oracle_engine import FakeOracleEngine
from tests.fakes.fake_retrieval_gate import FakeRetrievalGate


class _FakeSearch:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.called = False

    async def execute(self, question, top_k=None):
        self.called = True
        return self.hits


class _FakeSections:
    async def execute(self):
        return ["Bootcamps", "Programs"]


class _FakeConvRepo:
    async def create(self, conversation):
        return conversation

    async def get_by_id(self, cid):
        return None


class _FakeMsgRepo:
    def __init__(self):
        self.appended = []

    async def load_recent(self, cid):
        return []

    async def append(self, message):
        self.appended.append(message)


def _build(gate, search):
    action = AnswerQuestionAction(
        engine=FakeOracleEngine(answer="resposta do motor"),
        search=search,
        gate=gate,
        sections=_FakeSections(),
    )
    action.conversations = _FakeConvRepo()
    action.messages = _FakeMsgRepo()
    return action


async def _collect(stream):
    text, citations = "", None
    async for chunk in stream:
        if chunk.type == "text":
            text += chunk.text
        elif chunk.type == "sources":
            citations = chunk.citations
    return text, citations


@pytest.mark.asyncio
async def test_refuses_when_retrieval_wanted_but_nothing_found():
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=[]))

    _, stream, _ = await action.execute("qual a capital da Austrália?", None, None)
    text, citations = await _collect(stream)

    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    assert "Bootcamps e Programs" in text
    assert citations == []
    assert "resposta do motor" not in text


@pytest.mark.asyncio
async def test_greeting_is_not_refused_even_though_knowledge_is_empty():
    """A guarda: retrieve=False também dá knowledge vazio, mas deve ir ao motor."""
    search = _FakeSearch(hits=[])
    action = _build(FakeRetrievalGate(retrieve=False), search)

    _, stream, _ = await action.execute("oi, tudo bem?", None, None)
    text, _ = await _collect(stream)

    assert "resposta do motor" in text
    assert "Não encontrei informações" not in text
    assert search.called is False


@pytest.mark.asyncio
async def test_goes_to_the_engine_when_knowledge_was_found():
    from src.domain.shared.value_objects.citation import Citation
    from src.support.agent.ports import KnowledgeSnippet

    hits = [KnowledgeSnippet("trecho", Citation("notion", "Doc", "u", "s", "p"))]
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=hits))

    _, stream, _ = await action.execute("o que é o Web3 Bootcamp?", None, None)
    text, _ = await _collect(stream)

    assert "resposta do motor" in text


@pytest.mark.asyncio
async def test_refusal_answers_in_english_for_an_english_question():
    action = _build(FakeRetrievalGate(retrieve=True), _FakeSearch(hits=[]))

    _, stream, _ = await action.execute("what is the capital of Australia?", None, None)
    text, _ = await _collect(stream)

    assert text.startswith("I didn't find information about this in the knowledge base.")
    assert "Bootcamps and Programs" in text
