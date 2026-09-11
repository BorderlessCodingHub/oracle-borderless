from uuid import uuid4

import pytest

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.agent.tools import SEARCH_LESSON_TOOL_NAME, build_mentor_tools


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
