"""OpenTurnAction: o escopo 1 do turno (ADR-0020) — conversa (find-or-create
pelo id do cliente), access policy, recência, pergunta gravada, draft/signals.
Não monta `deps` nem dispara o grafo: isso é RunTurnAction, no escopo 2."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.open_turn_action import OpenTurnAction
from src.domain.conversations.dtos.opened_turn import OpenedTurn
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.support.agent.ports import AgentMessage, TurnSignals
from src.support.core.exceptions import NotFoundError


def _msg(content: str, role: str = "user", conversation_id=None) -> Message:
    return Message(
        uuid=uuid4(),
        conversation_id=conversation_id or uuid4(),
        role=role,
        content=content,
        created_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )


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
    """Fake acoplado: `load_recent` reflete o que já foi gravado. Assim o teste
    de ordem pega o bug de append-antes-de-load — a pergunta atual apareceria
    no histórico."""

    def __init__(self):
        self.appended = []

    async def append(self, message):
        self.appended.append(message)
        return message

    async def load_recent(self, cid):
        return [AgentMessage(role=m.role, content=m.content) for m in self.appended]


def _make(conv_repo, msg_repo) -> OpenTurnAction:
    action = OpenTurnAction()
    action.conversations = conv_repo
    action.messages = msg_repo
    return action


@pytest.mark.asyncio
async def test_unknown_conversation_id_creates_the_conversation_with_that_id():
    """ADR-0019: o threadId vem do cliente. Se não existe, a conversa nasce com
    ESSE id — nunca com um novo — para o cliente conseguir continuar o fio."""
    conv_repo, msg_repo = _FakeConvRepo(), _FakeMsgRepo()
    given = uuid4()

    turn = await _make(conv_repo, msg_repo).execute("qual o onboarding?", given, "a@x.com")

    assert isinstance(turn, OpenedTurn)
    assert conv_repo.created is not None
    assert conv_repo.created.uuid == given
    assert turn.conversation_id == given
    assert turn.question == "qual o onboarding?"
    assert conv_repo.created.title == "qual o onboarding?"
    assert conv_repo.created.user_email == "a@x.com"
    assert msg_repo.appended[0].role == "user"
    assert msg_repo.appended[0].content == "qual o onboarding?"


@pytest.mark.asyncio
async def test_known_conversation_id_is_reused_not_recreated():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    conv_repo = _FakeConvRepo(existing=existing)

    turn = await _make(conv_repo, _FakeMsgRepo()).execute("segunda pergunta", existing.uuid, "a@x.com")

    assert conv_repo.created is None
    assert turn.conversation_id == existing.uuid


@pytest.mark.asyncio
async def test_recency_is_loaded_before_appending_the_current_question():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    msg_repo = _FakeMsgRepo()
    msg_repo.appended.append(_msg("turno anterior", conversation_id=existing.uuid))

    turn = await _make(_FakeConvRepo(existing=existing), msg_repo).execute("nova pergunta", existing.uuid, "a@x.com")

    contents = [m.content for m in turn.history]
    assert contents == ["turno anterior"]
    assert "nova pergunta" not in contents
    assert [m.content for m in msg_repo.appended] == ["turno anterior", "nova pergunta"]


@pytest.mark.asyncio
async def test_mismatched_owner_propagates_not_found():
    """ADR-0017: conversa de outro usuário é 404 — nunca revela que existe."""
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    msg_repo = _FakeMsgRepo()

    with pytest.raises(NotFoundError):
        await _make(_FakeConvRepo(existing=existing), msg_repo).execute("oi", existing.uuid, "b@x.com")

    assert msg_repo.appended == []  # nada gravado para o intruso


@pytest.mark.asyncio
async def test_long_question_title_is_truncated_to_80_chars():
    conv_repo = _FakeConvRepo()

    await _make(conv_repo, _FakeMsgRepo()).execute("x" * 200, uuid4(), "a@x.com")

    assert len(conv_repo.created.title) == 80


@pytest.mark.asyncio
async def test_draft_carries_the_question_user_and_the_same_signals_object():
    """`turn.signals` É `turn.draft.signals`: RunTurnAction entrega o primeiro ao
    grafo e o controller lê o segundo — se fossem dois objetos, o trace
    absorveria zeros."""
    turn = await _make(_FakeConvRepo(), _FakeMsgRepo()).execute("oi", uuid4(), "a@x.com")

    assert isinstance(turn.signals, TurnSignals)
    assert turn.draft.signals is turn.signals
    assert turn.draft.question == "oi"
    assert turn.draft.user_email == "a@x.com"


@pytest.mark.asyncio
async def test_mode_and_locale_default_to_chat_and_pt_br():
    turn = await _make(_FakeConvRepo(), _FakeMsgRepo()).execute("oi", uuid4(), "a@x.com")

    assert turn.mode == "chat"
    assert turn.locale == "pt-BR"


@pytest.mark.asyncio
async def test_mode_and_locale_are_stored_on_the_opened_turn():
    """A barra manda mode="navigate"; a Action só guarda — quem decide o que
    fazer com isso é o grafo (Task 4)."""
    turn = await _make(_FakeConvRepo(), _FakeMsgRepo()).execute(
        "onde fica o onboarding?", uuid4(), "a@x.com", mode="navigate", locale="en",
    )

    assert turn.mode == "navigate"
    assert turn.locale == "en"


@pytest.mark.asyncio
async def test_history_tokens_are_estimated_from_the_loaded_recency():
    class _WithHistory(_FakeMsgRepo):
        async def load_recent(self, conversation_id):
            return [AgentMessage(role="user", content="a" * 400)]

    turn = await _make(_FakeConvRepo(), _WithHistory()).execute("oi", uuid4(), None)

    assert turn.draft.history_messages == 1
    assert turn.draft.history_tokens_est == 100  # 400 // 4


@pytest.mark.asyncio
async def test_new_conversation_is_born_with_the_turn_mode():
    conv_repo = _FakeConvRepo()

    await _make(conv_repo, _FakeMsgRepo()).execute("me leve ao blog", uuid4(), "a@x.com", mode="navigate")

    assert conv_repo.created.mode == "navigate"


@pytest.mark.asyncio
async def test_new_conversation_defaults_to_chat_mode():
    conv_repo = _FakeConvRepo()

    await _make(conv_repo, _FakeMsgRepo()).execute("oi", uuid4(), "a@x.com")

    assert conv_repo.created.mode == "chat"


@pytest.mark.asyncio
async def test_existing_conversation_keeps_its_original_mode():
    """Um turno `chat` sobre uma thread nascida `navigate` não a reclassifica."""
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None, mode="navigate")
    conv_repo = _FakeConvRepo(existing=existing)

    await _make(conv_repo, _FakeMsgRepo()).execute("continua", existing.uuid, "a@x.com", mode="chat")

    assert conv_repo.created is None
    assert existing.mode == "navigate"
