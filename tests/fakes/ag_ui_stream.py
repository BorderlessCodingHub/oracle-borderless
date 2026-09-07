"""Helpers de parsing de respostas AG-UI (ADR-0019), compartilhados entre os
testes de integração de `/conversations/ask`.

`events`/`event_types`/`text_of`/`sources_of` leem o corpo `data: {json}` que o
`EventEncoder` produz; `run_input` monta o `RunAgentInput` mínimo aceito pelo
`RunAgentRequest` (Task 6)."""

import json
from uuid import uuid4


def run_input(question: str, thread_id: str | None = None, run_id: str | None = None) -> dict:
    return {
        "threadId": thread_id or str(uuid4()),
        "runId": run_id or str(uuid4()),
        "messages": [{"id": str(uuid4()), "role": "user", "content": question}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def events(body: str) -> list[dict]:
    out = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def event_types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def text_of(events: list[dict]) -> str:
    return "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


def sources_of(events: list[dict]) -> list[dict]:
    custom = [e for e in events if e["type"] == "CUSTOM" and e["name"] == "oracle.sources"]
    assert len(custom) == 1, f"esperava 1 oracle.sources, achei {len(custom)}"
    return custom[0]["value"]["citations"]
