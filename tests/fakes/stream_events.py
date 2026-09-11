"""Helpers de leitura do fio `event:`/`data:` (ADR-0021), compartilhados pelos
testes de integração de `/conversations/ask`. `ask_body` monta o body
`{input, config}` que o `StreamEventsRequest` aceita."""

import json
from uuid import uuid4

STEP_NODES = ("gate", "retrieve", "refuse", "answer", "navigate")


def ask_body(
    question: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    mode: str | None = None,
    locale: str | None = None,
) -> dict:
    input_ = {"question": question}
    if mode is not None:
        input_["mode"] = mode
    if locale is not None:
        input_["locale"] = locale
    return {
        "input": input_,
        "config": {
            "run_id": run_id or str(uuid4()),
            "configurable": {"thread_id": thread_id or str(uuid4())},
        },
    }


def events(body: str) -> list[dict]:
    """Um dict por bloco SSE. Afirma o contrato `event: == data.event`."""
    out = []
    for block in body.split("\n\n"):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        event_lines = [line[6:].strip() for line in lines if line.startswith("event:")]
        data_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
        assert len(event_lines) == 1 and len(data_lines) == 1, f"bloco malformado: {block!r}"
        payload = json.loads(data_lines[0])
        assert payload["event"] == event_lines[0], f"event: {event_lines[0]} != data.event {payload['event']}"
        assert set(payload) == {"event", "name", "run_id", "tags", "metadata", "parent_ids", "data"}, sorted(payload)
        out.append(payload)
    return out


def event_names(evs: list[dict]) -> list[str]:
    return [e["event"] for e in evs]


def is_root(e: dict) -> bool:
    return e["parent_ids"] == []


def steps(evs: list[dict]) -> list[tuple[str, str]]:
    out = []
    for e in evs:
        if e["name"] in STEP_NODES and e["metadata"].get("langgraph_node") == e["name"]:
            if e["event"] == "on_chain_start":
                out.append((e["name"], "start"))
            elif e["event"] == "on_chain_end":
                out.append((e["name"], "end"))
    return out


def text_of(evs: list[dict]) -> str:
    text = ""
    for e in evs:
        if e["event"] == "on_chat_model_stream" and e["metadata"].get("langgraph_node") == "answer":
            text += e["data"]["chunk"].get("content") or ""
        elif e["event"] == "on_chain_stream" and is_root(e):
            mode, payload = e["data"]["chunk"]
            if mode == "updates":
                text += (payload.get("refuse") or {}).get("answer") or ""
    return text


def root_end(evs: list[dict]) -> dict:
    ends = [e for e in evs if e["event"] == "on_chain_end" and is_root(e)]
    assert len(ends) == 1, f"esperava 1 on_chain_end do raiz, achei {len(ends)}"
    return ends[0]


def sources_of(evs: list[dict]) -> list[dict]:
    return root_end(evs)["data"]["output"]["citations"]


def navigation_of(evs: list[dict]) -> dict | None:
    """O destino resolvido: o PRIMEIRO chunk `updates` do raiz que carrega
    `navigate.navigation` (antes do modelo terminar a frase). None se o turno
    não navegou."""
    for e in evs:
        if e["event"] == "on_chain_stream" and is_root(e):
            mode, payload = e["data"]["chunk"]
            if mode == "updates":
                nav = (payload.get("navigate") or {}).get("navigation")
                if nav:
                    return nav
    return None
