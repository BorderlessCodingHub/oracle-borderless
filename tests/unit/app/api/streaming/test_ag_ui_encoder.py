"""Tradução chunk -> evento AG-UI (ADR-0019). Função pura, sem HTTP."""

import json

from ag_ui.core import EventType

from src.app.api.streaming.ag_ui_encoder import (
    SOURCES_EVENT,
    STEP_EVENT,
    RunContext,
    encode,
    run_error,
    run_finished,
    run_started,
    to_events,
)
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)


def _ctx() -> RunContext:
    return RunContext(thread_id="t1", run_id="r1")


def _types(events):
    return [e.type for e in events]


def test_run_started_and_finished_echo_thread_and_run():
    ctx = _ctx()
    started, finished = run_started(ctx), run_finished(ctx)
    assert (started.type, started.thread_id, started.run_id) == (EventType.RUN_STARTED, "t1", "r1")
    assert (finished.type, finished.thread_id, finished.run_id) == (EventType.RUN_FINISHED, "t1", "r1")


def test_text_message_start_is_emitted_once_before_the_first_delta():
    ctx = _ctx()
    first = to_events(TextChunk(text="olá "), ctx)
    second = to_events(TextChunk(text="mundo"), ctx)

    assert _types(first) == [EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_CONTENT]
    assert first[0].message_id == ctx.message_id and first[0].role == "assistant"
    assert first[1].delta == "olá "
    assert _types(second) == [EventType.TEXT_MESSAGE_CONTENT]
    assert second[0].message_id == ctx.message_id


def test_empty_text_produces_no_event():
    assert to_events(TextChunk(text=""), _ctx()) == []


def test_sources_close_the_text_message_and_carry_the_citation_payload():
    ctx = _ctx()
    to_events(TextChunk(text="x"), ctx)
    events = to_events(SourcesChunk(citations=[Citation("notion", "Doc", "https://n/a", "trecho")]), ctx)

    assert _types(events) == [EventType.TEXT_MESSAGE_END, EventType.CUSTOM]
    assert events[0].message_id == ctx.message_id
    assert events[1].name == SOURCES_EVENT
    assert events[1].value == {
        "citations": [{"source_type": "notion", "title": "Doc", "url": "https://n/a", "snippet": "trecho"}]
    }


def test_sources_without_any_text_do_not_emit_a_text_end():
    events = to_events(SourcesChunk(citations=[]), _ctx())
    assert _types(events) == [EventType.CUSTOM]
    assert events[0].value == {"citations": []}


def test_steps_map_to_step_events_and_detail_to_a_custom_event():
    ctx = _ctx()
    assert _types(to_events(StepChunk(name="gate", phase="started"), ctx)) == [EventType.STEP_STARTED]
    finished = to_events(StepChunk(name="retrieve", phase="finished", detail={"kept": 4}), ctx)
    assert _types(finished) == [EventType.STEP_FINISHED, EventType.CUSTOM]
    assert finished[0].step_name == "retrieve"
    assert finished[1].name == STEP_EVENT
    assert finished[1].value == {"step": "retrieve", "kept": 4}
    # sem detalhe, sem CUSTOM
    assert _types(to_events(StepChunk(name="answer", phase="finished"), ctx)) == [EventType.STEP_FINISHED]


def test_tool_calls_hang_off_the_assistant_message():
    ctx = _ctx()
    start = to_events(ToolCallStartChunk(id="c1", name="web_search"), ctx)
    args = to_events(ToolCallArgsChunk(id="c1", delta='{"query":"psp"}'), ctx)
    end = to_events(ToolCallEndChunk(id="c1"), ctx)
    result = to_events(ToolCallResultChunk(id="c1", status="error"), ctx)

    assert _types(start) == [EventType.TOOL_CALL_START]
    assert (start[0].tool_call_id, start[0].tool_call_name, start[0].parent_message_id) == ("c1", "web_search", ctx.message_id)
    assert _types(args) == [EventType.TOOL_CALL_ARGS] and args[0].delta == '{"query":"psp"}'
    assert _types(end) == [EventType.TOOL_CALL_END] and end[0].tool_call_id == "c1"
    assert _types(result) == [EventType.TOOL_CALL_RESULT]
    assert result[0].tool_call_id == "c1"
    assert json.loads(result[0].content) == {"status": "error"}
    assert result[0].message_id != ctx.message_id  # o result é uma mensagem "tool" própria


def test_run_error_closes_an_open_text_message_then_errors():
    ctx = _ctx()
    to_events(TextChunk(text="parcial"), ctx)
    events = run_error(ctx, "erro ao gerar a resposta")
    assert _types(events) == [EventType.TEXT_MESSAGE_END, EventType.RUN_ERROR]
    assert events[1].message == "erro ao gerar a resposta"

    # sem texto aberto, só o erro
    assert _types(run_error(_ctx(), "x")) == [EventType.RUN_ERROR]


def test_encode_is_sse_data_only_in_camel_case():
    line = encode(to_events(StepChunk(name="gate", phase="started"), _ctx())[0])
    assert line == 'data: {"type":"STEP_STARTED","stepName":"gate"}\n\n'
