"""Composição da Action: conversa, access policy, mensagem e recência.

O que era gate/retrieval/recusa aqui virou nó do grafo — coberto em
`tests/unit/support/agent/graph/test_nodes.py` e `test_edges.py`. Estes
testes exercitam só o que sobrou na Action.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, KnowledgeSnippet
from src.support.core.exceptions import NotFoundError, UnauthorizedDomainError
from tests.fakes.fake_turn_graph import FakeTurnGraph


def _msg(content: str, role: str = "user", conversation_id=None) -> Message:
    return Message(
        uuid=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )


class _FakeSearch:
    """Por padrão devolve 1 trecho não-vazio: estes testes exercitam mecânica de
    conversa (título, persistência, ordem do histórico), não retrieval — o
    grafo é fake e nunca chama `search` de verdade."""

    def __init__(self, hits=None):
        self.hits = (
            hits
            if hits is not None
            else [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "s", "pid"))]
        )

    async def execute(self, question, top_k=None):
        return self.hits


class _FakeSections:
    async def execute(self):
        return ["Bootcamps", "Programs"]


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


def _make(graph, search, conv_repo, msg_repo):
    action = AnswerQuestionAction(graph=graph, search=search, sections=_FakeSections())
    action.conversations = conv_repo
    action.messages = msg_repo
    return action


@pytest.mark.asyncio
async def test_new_conversation_persists_user_and_sets_title():
    graph, conv_repo, msg_repo = FakeTurnGraph(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(graph, _FakeSearch(), conv_repo, msg_repo)

    conversation_id, stream, _ = await action.execute("qual o onboarding?", None, "a@x.com")

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
    action = _make(FakeTurnGraph(), _FakeSearch(), _FakeConvRepo(existing=None), _FakeMsgRepo())
    with pytest.raises(NotFoundError):
        await action.execute("oi", uuid4(), "a@x.com")


class _HistoryCapturingGraph(FakeTurnGraph):
    """`FakeTurnGraph` não guarda `history` — só `question`/`knowledge` (é o
    contrato do Step 1 do brief). Este subclasse local acrescenta a captura só
    para este teste, sem tocar no fake compartilhado."""

    def __init__(self):
        super().__init__()
        self.received_history = None

    async def start(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        self.received_history = history
        return await super().start(question, history, deps, signals, knowledge, extra_config)


@pytest.mark.asyncio
async def test_recency_loaded_before_appending_current_message():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    graph, msg_repo = _HistoryCapturingGraph(), _FakeMsgRepo()
    # turno ANTERIOR já persistido antes deste execute()
    msg_repo.appended.append(_msg("turno anterior", conversation_id=existing.uuid))
    action = _make(graph, _FakeSearch(), _FakeConvRepo(existing=existing), msg_repo)

    _, stream, _ = await action.execute("nova pergunta", existing.uuid, "a@x.com")
    [c async for c in stream]

    # histórico passado ao grafo = turnos anteriores, sem a pergunta atual.
    # Com o fake acoplado, se a Action gravasse antes de carregar, "nova pergunta"
    # apareceria aqui e o teste falharia.
    contents = [m.content for m in graph.received_history]
    assert contents == ["turno anterior"]
    assert "nova pergunta" not in contents


@pytest.mark.asyncio
async def test_mismatched_owner_propagates_unauthorized():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    action = _make(FakeTurnGraph(), _FakeSearch(), _FakeConvRepo(existing=existing), _FakeMsgRepo())

    with pytest.raises(UnauthorizedDomainError):
        await action.execute("oi", existing.uuid, "b@x.com")


@pytest.mark.asyncio
async def test_long_question_title_is_truncated_to_80_chars():
    graph, conv_repo, msg_repo = FakeTurnGraph(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(graph, _FakeSearch(), conv_repo, msg_repo)

    long_question = "x" * 200
    _, stream, _ = await action.execute(long_question, None, "a@x.com")
    [c async for c in stream]

    assert len(conv_repo.created.title) == 80


@pytest.mark.asyncio
async def test_signals_is_the_same_object_the_graph_receives():
    """Se o wiring se dividir em duas instâncias de TurnSignals, o controller
    absorveria zeros do draft mesmo com o grafo tendo escrito na sua cópia —
    prende que é o MESMO objeto que `draft.signals` carrega."""
    graph = FakeTurnGraph(tool_calls=2, input_tokens=123, output_tokens=45)
    action = _make(graph, _FakeSearch(), _FakeConvRepo(), _FakeMsgRepo())

    _, stream, draft = await action.execute("oi", None, "a@x.com")
    async for _ in stream:
        pass  # consome o stream para o fake de fato escrever em `signals`

    assert draft.signals is not None
    assert draft.signals.tool_calls == 2
    assert draft.signals.input_tokens == 123
    assert draft.signals.output_tokens == 45
