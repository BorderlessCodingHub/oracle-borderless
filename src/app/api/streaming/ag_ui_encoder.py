"""Tradução dos chunks do port para eventos AG-UI (ADR-0019).

Camada `app`: aqui — e só aqui, além do request schema — o protocolo existe. O
grafo fala em dataclasses (`src/support/agent/ports.py`); esta função pura as
converte nos eventos que o `EventEncoder` serializa como `data: {json}`.

Invariantes do contrato (spec 2026-09-04, seção 1.2):
- um único `messageId` de assistente por run; `TEXT_MESSAGE_START` sai uma vez,
  antes do primeiro delta; `TEXT_MESSAGE_END` antes das fontes (ou do erro);
- `TOOL_CALL_RESULT.content` é só `{"status": ...}` — nunca conteúdo de tool.
"""

import json
from dataclasses import dataclass, field

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from uuid6 import uuid7

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    AgentStreamChunk,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)

SOURCES_EVENT = "oracle.sources"
STEP_EVENT = "oracle.step"

_encoder = EventEncoder()
CONTENT_TYPE = _encoder.get_content_type()


@dataclass
class RunContext:
    """O que um run precisa lembrar entre chunks."""

    thread_id: str
    run_id: str
    message_id: str = field(default_factory=lambda: str(uuid7()))
    text_started: bool = False


def encode(event: BaseEvent) -> str:
    return _encoder.encode(event)


def run_started(ctx: RunContext) -> BaseEvent:
    return RunStartedEvent(type=EventType.RUN_STARTED, thread_id=ctx.thread_id, run_id=ctx.run_id)


def run_finished(ctx: RunContext) -> BaseEvent:
    return RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=ctx.thread_id, run_id=ctx.run_id)


def run_error(ctx: RunContext, message: str) -> list[BaseEvent]:
    """Falha no meio do stream: fecha o texto aberto e encerra com RUN_ERROR.
    Sem RUN_FINISHED depois — é o protocolo."""
    return [*_close_text(ctx), RunErrorEvent(type=EventType.RUN_ERROR, message=message)]


def _citation_payload(c: Citation) -> dict:
    return {"source_type": c.source_type, "title": c.title, "url": c.url, "snippet": c.snippet}


def _close_text(ctx: RunContext) -> list[BaseEvent]:
    if not ctx.text_started:
        return []
    ctx.text_started = False
    return [TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=ctx.message_id)]


def to_events(chunk: AgentStreamChunk, ctx: RunContext) -> list[BaseEvent]:
    match chunk:
        case TextChunk(text=text):
            if not text:
                return []
            out: list[BaseEvent] = []
            if not ctx.text_started:
                ctx.text_started = True
                out.append(
                    TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START, message_id=ctx.message_id, role="assistant"
                    )
                )
            out.append(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT, message_id=ctx.message_id, delta=text
                )
            )
            return out
        case SourcesChunk(citations=citations):
            return [
                *_close_text(ctx),
                CustomEvent(
                    type=EventType.CUSTOM,
                    name=SOURCES_EVENT,
                    value={"citations": [_citation_payload(c) for c in citations]},
                ),
            ]
        case StepChunk(name=name, phase="started"):
            return [StepStartedEvent(type=EventType.STEP_STARTED, step_name=name)]
        case StepChunk(name=name, detail=detail):
            out = [StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name)]
            if detail is not None:
                out.append(CustomEvent(type=EventType.CUSTOM, name=STEP_EVENT, value={"step": name, **detail}))
            return out
        case ToolCallStartChunk(id=tc_id, name=name):
            return [
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tc_id,
                    tool_call_name=name,
                    parent_message_id=ctx.message_id,
                )
            ]
        case ToolCallArgsChunk(id=tc_id, delta=delta):
            return [ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=tc_id, delta=delta)]
        case ToolCallEndChunk(id=tc_id):
            return [ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tc_id)]
        case ToolCallResultChunk(id=tc_id, status=status):
            return [
                ToolCallResultEvent(
                    type=EventType.TOOL_CALL_RESULT,
                    message_id=str(uuid7()),
                    tool_call_id=tc_id,
                    content=json.dumps({"status": status}),
                    role="tool",
                )
            ]
    return []
