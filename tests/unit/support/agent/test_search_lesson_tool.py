from uuid import uuid4

import pytest

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.agent.tools import SEARCH_LESSON_TOOL_NAME, build_mentor_tools
from src.support.core.context import CurrentAsyncSessionContext


class Signals:
    def __init__(self):
        self.tool_calls = 0


def snippet(text: str) -> KnowledgeSnippet:
    return KnowledgeSnippet(
        content=text,
        citation=Citation(source_type="lesson", title="Aula 3", url="/programs/base/m1/a1?t=750", snippet=text[:200]),
    )


def make_config(lesson_id, action):
    return {
        "configurable": {
            "signals": Signals(),
            "citations": [],
            "lesson_id": lesson_id,
            "lesson_distances": [],
            "question_embedding": [],
            "search_lesson_action": action,
        }
    }


class FakeAction:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []
        self.last_query_embedding: list[float] | None = None

    async def execute(self, lesson_id, query, top_k=None):
        self.calls.append((lesson_id, query))
        self.last_query_embedding = [0.1, 0.2]
        return self.rows


def the_tool():
    tools = build_mentor_tools()
    return next(t for t in tools if t.name == SEARCH_LESSON_TOOL_NAME)


@pytest.mark.asyncio
async def test_the_model_never_supplies_the_lesson_id():
    """O escopo vem do runtime, não do modelo — um aluno não pode pedir aula
    que não comprou por prompt (spec §2.1)."""
    tool = the_tool()
    assert "lesson_id" not in tool.args
    assert "query" in tool.args


@pytest.mark.asyncio
async def test_returns_wrapped_content_and_collects_citations():
    lesson_id = uuid4()
    action = FakeAction([(snippet("por volta de 12:30 falei de autorregressão"), 0.21)])
    config = make_config(lesson_id, action)

    out = await the_tool().ainvoke({"query": "autorregressão"}, config=config)

    assert "<<TOOL_CONTENT>>" in out and "<</TOOL_CONTENT>>" in out
    assert "autorregressão" in out
    assert action.calls[0][0] == lesson_id
    assert len(config["configurable"]["citations"]) == 1
    assert config["configurable"]["signals"].tool_calls == 1


@pytest.mark.asyncio
async def test_records_every_distance_for_the_trace():
    config = make_config(uuid4(), FakeAction([(snippet("a"), 0.42), (snippet("b"), 0.63)]))
    await the_tool().ainvoke({"query": "x"}, config=config)
    assert config["configurable"]["lesson_distances"] == [0.42, 0.63]
    assert config["configurable"]["question_embedding"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_an_empty_lesson_says_so_instead_of_failing():
    config = make_config(uuid4(), FakeAction([]))
    out = await the_tool().ainvoke({"query": "x"}, config=config)
    assert "nenhum trecho" in out.lower()


@pytest.mark.asyncio
async def test_a_failing_search_does_not_break_the_stream():
    class Boom:
        async def execute(self, lesson_id, query, top_k=None):
            raise RuntimeError("banco fora")

    config = make_config(uuid4(), Boom())
    out = await the_tool().ainvoke({"query": "x"}, config=config)
    assert "<<TOOL_CONTENT>>" in out
    assert "falha" in out.lower()


# --- I1: o embedding não pode sabotar uma busca que deu certo -------------


@pytest.mark.asyncio
async def test_a_none_embedding_and_a_missing_cfg_key_still_return_the_snippets():
    """`last_query_embedding is None` (fake de teste) e `question_embedding`
    ausente do cfg (chamador que não pré-semeou a chave): antes, a atribuição
    `cfg["question_embedding"][:] = ...` explodia ANTES das citações serem
    coletadas e virava "(falha ao buscar na aula...)" mesmo com trechos bons."""

    class ActionWithNoEmbedding:
        last_query_embedding = None

        async def execute(self, lesson_id, query, top_k=None):
            return [(snippet("trecho bom"), 0.2)]

    config = {
        "configurable": {
            "signals": Signals(),
            "citations": [],
            "lesson_id": uuid4(),
            "lesson_distances": [],
            # sem "question_embedding" de propósito
            "search_lesson_action": ActionWithNoEmbedding(),
        }
    }

    out = await the_tool().ainvoke({"query": "x"}, config=config)

    assert "falha" not in out.lower()
    assert "trecho bom" in out
    assert len(config["configurable"]["citations"]) == 1
    assert "question_embedding" not in config["configurable"]


# --- M7: mesma citação (mesma url) não duplica -----------------------------


@pytest.mark.asyncio
async def test_duas_buscas_com_o_mesmo_trecho_geram_uma_unica_citacao():
    action = FakeAction(
        [(snippet("mesmo trecho"), 0.2), (snippet("mesmo trecho"), 0.2)]
    )
    config = make_config(uuid4(), action)

    await the_tool().ainvoke({"query": "x"}, config=config)
    # segunda busca do tool loop, mesma action (mesmo url de volta)
    await the_tool().ainvoke({"query": "y"}, config=config)

    assert len(config["configurable"]["citations"]) == 1


# --- C1 (ruling C6): sem action injetada, a tool abre seu PRÓPRIO escopo ---


@pytest.mark.asyncio
async def test_without_an_injected_action_the_tool_opens_its_own_session_scope(monkeypatch):
    """`stream()` não tem sessão (ADR-0020) — quem quer banco aqui precisa abrir
    escopo próprio. O fake abaixo registra entrada/saída e planta uma sessão
    "nova" no ContextVar; a `FakeAction` confirma, de dentro de `execute`, que
    o repositório enxergaria essa sessão nova (nunca a do escopo 2, já fechada)."""
    fake_session = object()
    scope_state = {"entered": False, "exited": False}

    class FakeScope:
        async def __aenter__(self):
            scope_state["entered"] = True
            CurrentAsyncSessionContext.set(fake_session)
            return fake_session

        async def __aexit__(self, *exc):
            scope_state["exited"] = True
            CurrentAsyncSessionContext.clear()
            return False

    def fake_async_session_scope():
        return FakeScope()

    seen_session_during_execute = {}

    class FakeSearchLessonAction:
        def __init__(self, embeddings):
            self.embeddings = embeddings
            self.last_query_embedding = [0.1, 0.2]

        async def execute(self, lesson_id, query, top_k=None):
            seen_session_during_execute["session"] = CurrentAsyncSessionContext.get()
            return [(snippet("achado"), 0.3)]

    monkeypatch.setattr(
        "src.support.core.session_scope.async_session_scope", fake_async_session_scope
    )
    monkeypatch.setattr(
        "src.domain.lessons.actions.search_lesson_action.SearchLessonAction",
        FakeSearchLessonAction,
    )
    monkeypatch.setattr(
        "src.support.clients.embeddings.embeddings_client.get_embeddings_client",
        lambda: object(),
    )

    config = {
        "configurable": {
            "signals": Signals(),
            "citations": [],
            "lesson_id": uuid4(),
            "lesson_distances": [],
            "question_embedding": [],
            # sem "search_lesson_action": é o caminho não-injetado que o C1 cobre.
        }
    }

    out = await the_tool().ainvoke({"query": "x"}, config=config)

    assert "achado" in out
    assert scope_state == {"entered": True, "exited": True}
    assert seen_session_during_execute["session"] is fake_session
    # a saída do escopo limpou o ContextVar — não sobrou sessão pendurada.
    assert CurrentAsyncSessionContext.get() is None
