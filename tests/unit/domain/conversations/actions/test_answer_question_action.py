from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.support.agent.ports import AgentMessage, AgentStreamChunk
from src.support.core.exceptions import NotFoundError, UnauthorizedDomainError


def _msg(content: str, role: str = "user", conversation_id=None) -> Message:
    return Message(
        uuid=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )


class _FakeSearch:
    async def execute(self, question):
        return []


class _FakeEngine:
    def __init__(self):
        self.received_history = None
        self.received_question = None
        self.received_knowledge = None

    async def stream_answer(self, question, history, knowledge):
        self.received_history = history
        self.received_question = question
        self.received_knowledge = knowledge
        yield AgentStreamChunk(type="text", text="ok")


class _FakeConvRepo:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = None

    async def get_by_id(self, cid):
        return self.existing

    async def create(self, conversation):
        self.created = conversation
        return conversation


class _FakeMsgRepo:
    """Fake acoplado: `load_recent` reflete o que já foi gravado (simula ler as
    linhas persistidas). Assim o teste de ordem realmente pega o bug de
    append-antes-de-load — a pergunta atual apareceria no histórico."""

    def __init__(self):
        self.appended = []

    async def append(self, message):
        self.appended.append(message)
        return message

    async def load_recent(self, cid):
        return [AgentMessage(role=m.role, content=m.content) for m in self.appended]


def _make(engine, search, conv_repo, msg_repo, gate=None):
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    action = AnswerQuestionAction(
        engine=engine, search=search, gate=gate or FakeRetrievalGate(retrieve=True)
    )
    action.conversations = conv_repo
    action.messages = msg_repo
    return action


@pytest.mark.asyncio
async def test_new_conversation_persists_user_and_sets_title():
    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(engine, _FakeSearch(), conv_repo, msg_repo)

    conversation_id, stream = await action.execute("qual o onboarding?", None, "a@x.com")

    assert conv_repo.created is not None
    assert conv_repo.created.title == "qual o onboarding?"
    assert conv_repo.created.user_email == "a@x.com"
    assert conversation_id == conv_repo.created.uuid
    assert msg_repo.appended[0].role == "user"
    assert msg_repo.appended[0].content == "qual o onboarding?"
    # drena o stream
    chunks = [c async for c in stream]
    assert any(c.type == "text" for c in chunks)


@pytest.mark.asyncio
async def test_missing_conversation_id_raises_not_found():
    action = _make(_FakeEngine(), _FakeSearch(), _FakeConvRepo(existing=None), _FakeMsgRepo())
    with pytest.raises(NotFoundError):
        await action.execute("oi", uuid4(), "a@x.com")


@pytest.mark.asyncio
async def test_recency_loaded_before_appending_current_message():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    engine, msg_repo = _FakeEngine(), _FakeMsgRepo()
    # turno ANTERIOR já persistido antes deste execute()
    msg_repo.appended.append(_msg("turno anterior", conversation_id=existing.uuid))
    action = _make(engine, _FakeSearch(), _FakeConvRepo(existing=existing), msg_repo)

    _, stream = await action.execute("nova pergunta", existing.uuid, "a@x.com")
    [c async for c in stream]

    # histórico passado ao engine = turnos anteriores, sem a pergunta atual.
    # Com o fake acoplado, se a Action gravasse antes de carregar, "nova pergunta"
    # apareceria aqui e o teste falharia.
    contents = [m.content for m in engine.received_history]
    assert contents == ["turno anterior"]
    assert "nova pergunta" not in contents


@pytest.mark.asyncio
async def test_mismatched_owner_propagates_unauthorized():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    action = _make(_FakeEngine(), _FakeSearch(), _FakeConvRepo(existing=existing), _FakeMsgRepo())

    with pytest.raises(UnauthorizedDomainError):
        await action.execute("oi", existing.uuid, "b@x.com")


@pytest.mark.asyncio
async def test_long_question_title_is_truncated_to_80_chars():
    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(engine, _FakeSearch(), conv_repo, msg_repo)

    long_question = "x" * 200
    _, stream = await action.execute(long_question, None, "a@x.com")
    [c async for c in stream]

    assert len(conv_repo.created.title) == 80


class _RecordingSearch:
    def __init__(self):
        self.calls = []

    async def execute(self, query):
        self.calls.append(query)
        from src.support.agent.ports import KnowledgeSnippet
        from src.domain.shared.value_objects.citation import Citation

        return [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "t", "a"))]


@pytest.mark.asyncio
async def test_gate_skip_injects_no_knowledge_and_skips_search():
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    search = _RecordingSearch()
    action = _make(engine, search, conv_repo, msg_repo, gate=FakeRetrievalGate(retrieve=False))

    _cid, stream = await action.execute("valeu!", None, "a@x.com")
    async for _ in stream:  # drena o stream
        pass

    assert search.calls == []  # não recuperou
    assert engine.received_knowledge == []


@pytest.mark.asyncio
async def test_gate_retrieve_uses_rewritten_query():
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    search = _RecordingSearch()
    gate = FakeRetrievalGate(retrieve=True, search_query="renovação de PSP")
    action = _make(engine, search, conv_repo, msg_repo, gate=gate)

    _cid, stream = await action.execute("e as renovações?", None, "a@x.com")
    async for _ in stream:
        pass

    assert search.calls == ["renovação de PSP"]  # query reescrita, não a crua
    assert engine.received_question == "e as renovações?"  # engine recebe pergunta original
