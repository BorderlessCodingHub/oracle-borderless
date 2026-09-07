"""Serialização do GraphEvent em SSE (ADR-0021). Função pura, sem HTTP.
`event:` repete `data.event`; os sete campos sempre presentes; Citation sem page_id."""

import json

from src.app.api.streaming.stream_event_encoder import CONTENT_TYPE, ERROR_EVENT, encode, error_event
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import ROOT_NAME, GraphEvent


def _parse(block: str) -> tuple[str, dict]:
    assert block.endswith("\n\n")
    event_line, data_line = block[:-2].split("\n")
    assert event_line.startswith("event: ") and data_line.startswith("data: ")
    return event_line[7:], json.loads(data_line[6:])


def test_encode_writes_event_and_data_with_all_seven_fields_in_order():
    ev = GraphEvent(event="on_chain_start", name="gate", run_id="r1", tags=["graph:step:1"], metadata={"langgraph_node": "gate", "thread_id": "t1"}, parent_ids=["root"], data={})

    name, payload = _parse(encode(ev))

    assert name == "on_chain_start"
    assert list(payload) == ["event", "name", "run_id", "tags", "metadata", "parent_ids", "data"]
    assert payload == {"event": "on_chain_start", "name": "gate", "run_id": "r1", "tags": ["graph:step:1"], "metadata": {"langgraph_node": "gate", "thread_id": "t1"}, "parent_ids": ["root"], "data": {}}


def test_citations_are_serialised_without_page_id_and_text_is_not_ascii_escaped():
    c = Citation("notion", "Doc ção", "https://n/a", "trecho", page_id="segredo")
    ev = GraphEvent(event="on_chain_end", name=ROOT_NAME, run_id="r1", tags=[], metadata={}, parent_ids=[], data={"output": {"outcome": "answer", "citations": [c]}})

    block = encode(ev)
    _, payload = _parse(block)

    assert payload["data"]["output"]["citations"] == [{"source_type": "notion", "title": "Doc ção", "url": "https://n/a", "snippet": "trecho"}]
    assert "segredo" not in block
    assert "Doc ção" in block  # ensure_ascii=False


def test_error_event_is_a_root_on_chain_error_with_the_thread_id():
    ev = error_event("r1", "t1", "erro ao gerar a resposta")

    assert ev.event == ERROR_EVENT == "on_chain_error"
    assert (ev.name, ev.run_id, ev.parent_ids, ev.is_root) == (ROOT_NAME, "r1", [], True)
    assert ev.metadata == {"thread_id": "t1"}
    assert ev.data == {"error": "erro ao gerar a resposta"}
    name, payload = _parse(encode(ev))
    assert name == "on_chain_error" and payload["data"] == {"error": "erro ao gerar a resposta"}


def test_content_type_is_event_stream():
    assert CONTENT_TYPE == "text/event-stream"
