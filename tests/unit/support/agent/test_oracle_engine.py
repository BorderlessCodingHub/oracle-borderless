import pytest

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.oracle_engine import OracleEngine
from src.support.agent.ports import AgentStreamChunk, KnowledgeSnippet, TurnMetrics


@pytest.mark.asyncio
async def test_engine_streams_text_and_final_sources():
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    engine = OracleEngine(model=TestModel())
    knowledge = [KnowledgeSnippet("o onboarding leva 7 dias", Citation("notion", "Onboarding", "u", "s", "pid"))]

    chunks = [c async for c in engine.stream_answer("quantos dias?", [], knowledge)]

    assert any(c.type == "text" for c in chunks)
    sources = [c for c in chunks if c.type == "sources"]
    assert len(sources) == 1
    # a citação da base injetada deve aparecer nas fontes finais
    assert any(cit.title == "Onboarding" for cit in sources[0].citations)


@pytest.mark.asyncio
async def test_enable_tools_false_registers_no_tools_on_the_model():
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    tm = TestModel()
    engine = OracleEngine(model=tm, enable_tools=False)
    knowledge = [KnowledgeSnippet("o onboarding leva 7 dias", Citation("notion", "Onboarding", "u", "s", "pid"))]

    _ = [c async for c in engine.stream_answer("quantos dias?", [], knowledge)]

    assert tm.last_model_request_parameters.function_tools == []


@pytest.mark.asyncio
async def test_enable_tools_default_true_registers_web_search_and_fetch_notion_page():
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    tm = TestModel()
    engine = OracleEngine(model=tm)  # default enable_tools=True
    knowledge = [KnowledgeSnippet("o onboarding leva 7 dias", Citation("notion", "Onboarding", "u", "s", "pid"))]

    _ = [c async for c in engine.stream_answer("quantos dias?", [], knowledge)]

    tool_names = {t.name for t in tm.last_model_request_parameters.function_tools}
    assert tool_names == {"web_search", "fetch_notion_page"}


@pytest.mark.asyncio
async def test_stream_answer_accepts_metrics_kwarg_without_raising():
    """`AnswerQuestionAction` sempre chama `stream_answer(..., metrics=metrics)`
    (ver answer_question_action.py) — o motor real precisa aceitar o parâmetro
    mesmo sem usá-lo ainda (uso real vem na Task 5), senão todo turno de
    produção levanta TypeError."""
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    engine = OracleEngine(model=TestModel(), enable_tools=False)
    knowledge = [KnowledgeSnippet("o onboarding leva 7 dias", Citation("notion", "Onboarding", "u", "s", "pid"))]

    chunks = [
        c async for c in engine.stream_answer("quantos dias?", [], knowledge, metrics=TurnMetrics())
    ]

    assert any(c.type == "text" for c in chunks)
