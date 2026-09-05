"""RunTurnAction: o escopo 2 do turno (ADR-0020). Monta os `deps` NO ESCOPO DE
SESSÃO EM QUE É CHAMADA — os repositórios capturam a sessão do ContextVar no
__init__ (regra 3) — e dispara `graph.run()`. Espelha
tests/unit/evals/test_harness_session_scope.py."""

from uuid import uuid4

import pytest

from src.domain.conversations.actions.run_turn_action import RunTurnAction, _NearestDistance
from src.domain.conversations.dtos.opened_turn import OpenedTurn
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.ports import AgentMessage, TurnSignals
from src.support.core.context import CurrentAsyncSessionContext
from tests.fakes.fake_turn_graph import FakeTurnGraph


class _FakeSession:
    """Só um sentinela — nada aqui toca banco."""


class _FakeEmbeddings:
    async def embed_query(self, query):
        return [0.0]


def _turn() -> OpenedTurn:
    signals = TurnSignals()
    draft = TurnTraceDraft(question="o que é PSP?", user_email="a@x.com")
    draft.signals = signals
    return OpenedTurn(
        conversation_id=uuid4(),
        question="o que é PSP?",
        history=[AgentMessage(role="user", content="antes")],
        draft=draft,
        signals=signals,
    )


@pytest.fixture
def sentinel_session():
    session = _FakeSession()
    CurrentAsyncSessionContext.set(session)
    try:
        yield session
    finally:
        CurrentAsyncSessionContext.clear()


def test_deps_are_built_with_the_session_current_at_call_time():
    """Sessão A no momento da construção, sessão B no momento do `execute()` —
    se `RunTurnAction.__init__` chegasse a montar os deps (regressão), os
    repositórios capturariam A e este teste pegaria isso."""
    session_a = _FakeSession()
    graph = FakeTurnGraph()
    CurrentAsyncSessionContext.set(session_a)
    try:
        action = RunTurnAction(graph, _FakeEmbeddings())
    finally:
        CurrentAsyncSessionContext.clear()

    session_b = _FakeSession()
    CurrentAsyncSessionContext.set(session_b)
    try:
        action.execute(_turn())
    finally:
        CurrentAsyncSessionContext.clear()

    deps = graph.received_deps
    assert deps is not None
    assert deps.search.chunk_repo.session is session_b
    assert deps.sections.documents.session is session_b
    assert isinstance(deps.nearest, _NearestDistance)
    assert deps.nearest._chunks.session is session_b
    assert deps.search.chunk_repo.session is not session_a


def test_execute_is_synchronous_and_forwards_question_history_and_signals(sentinel_session):
    graph = FakeTurnGraph()
    turn = _turn()

    run = RunTurnAction(graph, _FakeEmbeddings()).execute(turn)

    assert run is graph.last_run
    assert graph.question == "o que é PSP?"
    assert graph.received_history is turn.history
    assert graph.received_signals is turn.signals
    assert graph.knowledge is None  # o turno real nunca pré-semeia knowledge


def test_the_refusal_builder_is_the_domain_one(sentinel_session):
    from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply

    graph = FakeTurnGraph()

    RunTurnAction(graph, _FakeEmbeddings()).execute(_turn())

    assert graph.received_deps.refusal is build_out_of_scope_reply


# --- _NearestDistance --------------------------------------------------------


class _EmbeddingsSpy:
    SENTINEL_VECTOR = [0.11, 0.22, 0.33]

    def __init__(self):
        self.received_query = None

    async def embed_query(self, query):
        self.received_query = query
        return self.SENTINEL_VECTOR


class _SearchWithEmbeddings:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class _ChunksSpy:
    def __init__(self, nearest: float | None = 0.61):
        self._nearest = nearest
        self.received_vector = None

    async def nearest_distance(self, embedding):
        self.received_vector = embedding
        return self._nearest


@pytest.mark.asyncio
async def test_nearest_distance_adapter_chains_embed_query_then_nearest_distance():
    """Guardrail do caminho de recusa: `refuse_node` engole qualquer exceção
    deste adapter de propósito, então um adapter quebrado devolveria None em
    silêncio — daí testá-lo isolado."""
    embeddings = _EmbeddingsSpy()
    chunks = _ChunksSpy(nearest=0.61)

    distance = await _NearestDistance(_SearchWithEmbeddings(embeddings), chunks).execute("renovação de PSP")

    assert embeddings.received_query == "renovação de PSP"
    assert chunks.received_vector == _EmbeddingsSpy.SENTINEL_VECTOR
    assert distance == 0.61


@pytest.mark.asyncio
async def test_nearest_distance_adapter_returns_none_when_chunks_repo_says_so():
    distance = await _NearestDistance(_SearchWithEmbeddings(_EmbeddingsSpy()), _ChunksSpy(nearest=None)).execute("q")

    assert distance is None
