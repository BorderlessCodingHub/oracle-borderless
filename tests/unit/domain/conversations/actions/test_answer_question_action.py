"""Composição da Action: conversa, access policy, mensagem e recência.

O que era gate/retrieval/recusa aqui virou nó do grafo — coberto em
`tests/unit/support/agent/graph/test_nodes.py` e `test_edges.py`. Estes
testes exercitam só o que sobrou na Action.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.conversations.actions.answer_question_action import (
    AnswerQuestionAction,
    _NearestDistance,
)
from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.entities.message import Message
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, KnowledgeSnippet, TextChunk
from src.support.core.exceptions import NotFoundError
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
async def test_unknown_conversation_id_creates_the_conversation_with_that_id():
    """ADR-0019: o threadId vem do cliente. Se não existe, a conversa nasce com
    ESSE id — nunca com um novo — para o cliente conseguir continuar o fio."""
    graph, conv_repo, msg_repo = FakeTurnGraph(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(graph, _FakeSearch(), conv_repo, msg_repo)
    given = uuid4()

    conversation_id, stream, _ = await action.execute("qual o onboarding?", given, "a@x.com")

    assert conv_repo.created is not None
    assert conv_repo.created.uuid == given
    assert conversation_id == given
    assert conv_repo.created.title == "qual o onboarding?"
    assert conv_repo.created.user_email == "a@x.com"
    assert msg_repo.appended[0].role == "user"
    assert msg_repo.appended[0].content == "qual o onboarding?"
    chunks = [c async for c in stream]
    assert any(isinstance(c, TextChunk) for c in chunks)


@pytest.mark.asyncio
async def test_known_conversation_id_is_reused_not_recreated():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    conv_repo = _FakeConvRepo(existing=existing)
    action = _make(FakeTurnGraph(), _FakeSearch(), conv_repo, _FakeMsgRepo())

    conversation_id, stream, _ = await action.execute("segunda pergunta", existing.uuid, "a@x.com")
    [c async for c in stream]

    assert conv_repo.created is None
    assert conversation_id == existing.uuid


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
async def test_mismatched_owner_propagates_not_found():
    # ADR-0017: conversa de outro usuário é 404 — nunca revela que existe.
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    action = _make(FakeTurnGraph(), _FakeSearch(), _FakeConvRepo(existing=existing), _FakeMsgRepo())

    with pytest.raises(NotFoundError):
        await action.execute("oi", existing.uuid, "b@x.com")


@pytest.mark.asyncio
async def test_long_question_title_is_truncated_to_80_chars():
    graph, conv_repo, msg_repo = FakeTurnGraph(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(graph, _FakeSearch(), conv_repo, msg_repo)

    long_question = "x" * 200
    _, stream, _ = await action.execute(long_question, uuid4(), "a@x.com")
    [c async for c in stream]

    assert len(conv_repo.created.title) == 80


@pytest.mark.asyncio
async def test_signals_is_the_same_object_the_graph_receives():
    """Se o wiring se dividir em duas instâncias de TurnSignals, o controller
    absorveria zeros do draft mesmo com o grafo tendo escrito na sua cópia —
    prende que é o MESMO objeto que `draft.signals` carrega."""
    graph = FakeTurnGraph(tool_calls=2, input_tokens=123, output_tokens=45)
    action = _make(graph, _FakeSearch(), _FakeConvRepo(), _FakeMsgRepo())

    _, stream, draft = await action.execute("oi", uuid4(), "a@x.com")
    async for _ in stream:
        pass  # consome o stream para o fake de fato escrever em `signals`

    assert draft.signals is not None
    assert draft.signals.tool_calls == 2
    assert draft.signals.input_tokens == 123
    assert draft.signals.output_tokens == 45


class _EmbeddingsSpy:
    """Registra a query recebida e devolve um vetor sentinela — permite provar
    que `_NearestDistance` encadeia embed_query -> nearest_distance NA ORDEM
    certa e com os argumentos certos, não que o `except` do caminho de recusa
    engoliu uma falha e devolveu None por acidente."""

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
    """Registra o vetor recebido e devolve uma distância não-trivial — se o
    adapter passasse a query crua (ou nada) em vez do vetor de
    `embed_query`, este fake pegaria isso na asserção do vetor recebido."""

    def __init__(self, nearest: float | None = 0.61):
        self._nearest = nearest
        self.received_vector = None

    async def nearest_distance(self, embedding):
        self.received_vector = embedding
        return self._nearest


@pytest.mark.asyncio
async def test_nearest_distance_adapter_chains_embed_query_then_nearest_distance():
    """Guardrail do caminho de recusa: `_NearestDistance.execute()` precisa
    encadear `search.embeddings.embed_query(query)` -> `chunks.nearest_distance
    (vector)`, NESSA ORDEM, propagando o vetor exato — não a query crua, não um
    vetor vazio. `refuse_node` engole qualquer exceção deste adapter de
    propósito (observabilidade não pode custar a recusa), então um adapter
    quebrado devolveria `None` silenciosamente e nenhum teste indireto pegaria
    isso — daí testar o adapter isolado, sem depender do grafo."""
    embeddings = _EmbeddingsSpy()
    search = _SearchWithEmbeddings(embeddings)
    chunks = _ChunksSpy(nearest=0.61)
    adapter = _NearestDistance(search, chunks)

    distance = await adapter.execute("renovação de PSP")

    assert embeddings.received_query == "renovação de PSP"
    assert chunks.received_vector == _EmbeddingsSpy.SENTINEL_VECTOR
    assert distance == 0.61


@pytest.mark.asyncio
async def test_nearest_distance_adapter_returns_none_when_chunks_repo_says_so():
    """Sem chunk nenhum na base, `nearest_distance` devolve `None` de verdade —
    o adapter só repassa, não mascara `None` genuíno como falha nem vice-versa."""
    embeddings = _EmbeddingsSpy()
    search = _SearchWithEmbeddings(embeddings)
    chunks = _ChunksSpy(nearest=None)
    adapter = _NearestDistance(search, chunks)

    distance = await adapter.execute("pergunta qualquer")

    assert distance is None


class _DepsCapturingGraph(FakeTurnGraph):
    """`FakeTurnGraph` não guarda `deps` (não precisa, para o resto da suíte) —
    este subclasse local captura só para provar que a Action monta
    `TurnDependencies.nearest` com um adapter de verdade, não `None`."""

    def __init__(self):
        super().__init__()
        self.received_deps = None

    async def start(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        self.received_deps = deps
        return await super().start(question, history, deps, signals, knowledge, extra_config)


@pytest.mark.asyncio
async def test_action_wires_turn_dependencies_with_a_working_nearest_adapter():
    """Sem isto, `TurnDependencies.nearest=None` chegaria ao grafo e o nó de
    recusa perderia a medição de distância silenciosamente — nenhum teste do
    grafo pegaria isso porque o grafo confia no que a Action lhe entrega."""
    graph = _DepsCapturingGraph()
    action = _make(graph, _FakeSearch(), _FakeConvRepo(), _FakeMsgRepo())

    _, stream, _ = await action.execute("oi", uuid4(), "a@x.com")
    async for _ in stream:
        pass

    assert graph.received_deps is not None
    assert graph.received_deps.nearest is not None
    assert isinstance(graph.received_deps.nearest, _NearestDistance)
