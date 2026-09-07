from src.support.agent.ports import (
    AgentMessage,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)
from src.domain.shared.value_objects.citation import Citation


def test_text_chunk_carries_text():
    assert TextChunk(text="olá").text == "olá"


def test_sources_chunk_defaults_to_no_citations():
    assert SourcesChunk().citations == []
    c = SourcesChunk(citations=[Citation("web", "T", "u", "s")])
    assert len(c.citations) == 1


def test_step_chunk_detail_is_optional():
    started = StepChunk(name="gate", phase="started")
    finished = StepChunk(name="retrieve", phase="finished", detail={"kept": 3})
    assert started.detail is None
    assert finished.detail == {"kept": 3}


def test_tool_call_chunks_are_plain_dataclasses():
    assert ToolCallStartChunk(id="c1", name="web_search").name == "web_search"
    assert ToolCallArgsChunk(id="c1", delta='{"q').delta == '{"q'
    assert ToolCallEndChunk(id="c1").id == "c1"
    assert ToolCallResultChunk(id="c1", status="error").status == "error"


def test_agent_message():
    m = AgentMessage(role="user", content="oi")
    assert m.role == "user"


def test_knowledge_snippet_carries_content_and_citation():
    snip = KnowledgeSnippet(
        content="texto",
        citation=Citation("notion", "Doc", "https://n/a", "trecho", "pid"),
    )
    assert snip.content == "texto"
    assert snip.citation.is_notion()


def test_retrieval_decision_holds_flag_and_query():
    from src.support.agent.ports import RetrievalDecision

    d = RetrievalDecision(retrieve=True, search_query="renovação de PSP")
    assert d.retrieve is True
    assert d.search_query == "renovação de PSP"


def test_small_model_and_timeout_settings_have_defaults():
    from src.support.core.settings import settings

    assert settings.ANTHROPIC_SMALL_MODEL
    assert settings.OPENAI_SMALL_MODEL
    assert settings.GATE_TIMEOUT_SECONDS > 0


def test_signals_default_to_an_unmeasured_turn():
    from src.support.agent.ports import TurnSignals

    s = TurnSignals()
    assert s.outcome == "answer"
    assert s.tool_calls == 0
    assert s.input_tokens is None
    assert s.gate_degraded is False
    assert s.retrieval_ran is False
