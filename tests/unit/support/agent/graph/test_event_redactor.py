"""A única barreira entre o state do grafo e o cliente (regra 4, ADR-0021).
Os eventos crus aqui são cópias fiéis do que `astream_events` produziu na
sonda de 07/09 sobre o grafo real."""

from langchain_core.messages import AIMessageChunk, ToolMessage

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.runner import EventRedactor, _project
from src.support.agent.ports import ROOT_NAME

SECRET = "SEGREDO-DO-STATE"
FORBIDDEN_KEYS = {"messages", "knowledge", "question", "history", "search_query", "preset_knowledge", "user_hash", "page_id"}


def _raw(event, name, data, node=None, root=False, run_id="r", **meta):
    metadata = {"thread_id": "t1", "user_hash": "H", "ls_integration": "x", **meta}
    if node:
        metadata.update({"langgraph_node": node, "langgraph_step": 1, "langgraph_path": ("__pregel_pull", node), "langgraph_checkpoint_ns": f"{node}:abc"})
    return {"event": event, "name": name, "run_id": run_id, "tags": ["graph:step:1"], "metadata": metadata, "parent_ids": [] if root else ["root"], "data": data}


def _state(**extra):
    return {"question": "o que é PSP?", "history": [], "preset_knowledge": False, "messages": [SECRET], "knowledge": [SECRET, SECRET], "search_query": "q", **extra}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _keys(v)


def _assert_clean(ev):
    assert ev is not None
    assert not (set(_keys(ev.data)) & FORBIDDEN_KEYS), f"chave proibida em {ev.data}"
    assert SECRET not in repr(ev.data)
    assert set(ev.metadata) <= {"langgraph_node", "langgraph_step", "thread_id", "ls_provider", "ls_model_name"}
    assert ev.metadata["thread_id"] == "t1"


# --- projeção -----------------------------------------------------------------


def test_project_keeps_only_the_public_keys_and_counts_knowledge():
    c = Citation("notion", "Doc", "https://n/a", "trecho", page_id="pid")
    out = _project(_state(retrieve=True, degraded=False, answer="Não encontrei.", citations=[c], outcome="refusal"))

    assert out == {"retrieve": True, "degraded": False, "answer": "Não encontrei.", "outcome": "refusal", "kept": 2, "citations": [c]}
    assert _project({"messages": [SECRET]}) == {}
    assert _project(None) == {}


# --- raiz -----------------------------------------------------------------------


def test_root_start_carries_no_input():
    ev = EventRedactor().redact(_raw("on_chain_start", ROOT_NAME, {"input": _state()}, root=True))
    _assert_clean(ev)
    assert (ev.event, ev.name, ev.is_root, ev.data) == ("on_chain_start", ROOT_NAME, True, {})
    assert ev.tags == ["graph:step:1"] and ev.run_id == "r"


def test_root_stream_projects_updates_per_node_and_values_as_a_whole():
    r = EventRedactor()
    updates = r.redact(_raw("on_chain_stream", ROOT_NAME, {"chunk": ("updates", {"retrieve": {"knowledge": [SECRET], "search_query": "q"}})}, root=True))
    values = r.redact(_raw("on_chain_stream", ROOT_NAME, {"chunk": ("values", _state(retrieve=True, degraded=False))}, root=True))
    tools = r.redact(_raw("on_chain_stream", ROOT_NAME, {"chunk": ("updates", {"tools": {"messages": [SECRET]}})}, root=True))

    for ev in (updates, values, tools):
        _assert_clean(ev)
    assert updates.data == {"chunk": ["updates", {"retrieve": {"kept": 1}}]}
    assert values.data == {"chunk": ["values", {"retrieve": True, "degraded": False, "kept": 2}]}
    assert tools.data == {"chunk": ["updates", {"tools": {}}]}


def test_root_end_projects_the_final_state():
    c = Citation("notion", "Doc", "https://n/a", "trecho")
    ev = EventRedactor().redact(_raw("on_chain_end", ROOT_NAME, {"output": _state(citations=[c], outcome="answer")}, root=True))
    _assert_clean(ev)
    assert ev.data == {"output": {"outcome": "answer", "kept": 2, "citations": [c]}}


# --- nós ----------------------------------------------------------------------


def test_node_start_and_end_pass_for_step_nodes_only_and_never_carry_input():
    r = EventRedactor()
    start = r.redact(_raw("on_chain_start", "retrieve", {"input": _state()}, node="retrieve"))
    end = r.redact(_raw("on_chain_end", "retrieve", {"output": {"knowledge": [SECRET], "search_query": "q"}, "input": _state()}, node="retrieve"))

    _assert_clean(start)
    _assert_clean(end)
    assert start.data == {} and start.node == "retrieve"
    assert end.data == {"output": {"kept": 1}}
    assert r.redact(_raw("on_chain_start", "tools", {"input": _state()}, node="tools")) is None
    assert r.redact(_raw("on_chain_end", "tools", {"output": {"messages": [SECRET]}}, node="tools")) is None


def test_edges_start_node_and_internal_runnables_are_dropped():
    r = EventRedactor()
    assert r.redact(_raw("on_chain_start", "__start__", {"input": _state()}, node="__start__")) is None
    assert r.redact(_raw("on_chain_start", "route_entry", {"input": _state()}, node="__start__")) is None
    assert r.redact(_raw("on_chain_end", "should_retrieve", {"output": "retrieve"}, node="gate")) is None
    assert r.redact(_raw("on_chain_start", "RunnableSequence", {"input": "x"}, node="gate")) is None
    assert r.redact(_raw("on_chain_stream", "gate", {"chunk": {"retrieve": True}}, node="gate")) is None
    assert r.redact(_raw("on_chat_model_start", "ChatAnthropic", {"input": {"messages": [[SECRET]]}}, node="answer")) is None
    assert r.redact(_raw("on_chat_model_end", "ChatAnthropic", {"output": SECRET}, node="answer")) is None


def test_answer_opens_once_and_its_end_is_held_until_asked():
    r = EventRedactor()
    first = r.redact(_raw("on_chain_start", "answer", {"input": _state()}, node="answer"))
    end1 = r.redact(_raw("on_chain_end", "answer", {"output": {"messages": [SECRET], "citations": [], "outcome": "answer"}}, node="answer", run_id="a1"))
    again = r.redact(_raw("on_chain_start", "answer", {"input": _state()}, node="answer"))
    end2 = r.redact(_raw("on_chain_end", "answer", {"output": {"messages": [SECRET], "citations": [], "outcome": "answer"}}, node="answer", run_id="a2"))

    assert first is not None and first.data == {}
    assert again is None
    assert end1 is None and end2 is None
    held = r.pending_answer_end
    _assert_clean(held)
    assert (held.event, held.name, held.run_id, held.data) == ("on_chain_end", "answer", "a2", {"output": {"outcome": "answer", "citations": []}})


# --- modelo -------------------------------------------------------------------


def test_answer_tokens_are_flattened_and_empty_chunks_are_dropped():
    r = EventRedactor()
    text = r.redact(_raw("on_chat_model_stream", "ChatAnthropic", {"chunk": AIMessageChunk(content=[{"type": "text", "text": "Renov"}], id="m1")}, node="answer", ls_provider="anthropic", ls_model_name="claude", ls_model_type="chat"))
    empty = r.redact(_raw("on_chat_model_stream", "ChatAnthropic", {"chunk": AIMessageChunk(content="", tool_call_chunks=[{"name": "fetch_notion_page", "args": '{"page_id":"pid"}', "id": "c1", "index": 0, "type": "tool_call_chunk"}])}, node="answer"))
    gate = r.redact(_raw("on_chat_model_stream", "ChatOpenAI", {"chunk": AIMessageChunk(content="x")}, node="gate"))

    _assert_clean(text)
    assert text.data == {"chunk": {"content": "Renov", "id": "m1"}}
    assert text.metadata["ls_provider"] == "anthropic" and text.metadata["ls_model_name"] == "claude"
    assert empty is None
    assert gate is None


# --- tools --------------------------------------------------------------------


def test_tool_start_carries_input_only_for_web_search():
    r = EventRedactor()
    web = r.redact(_raw("on_tool_start", "web_search", {"input": {"query": "psp"}}, node="tools"))
    notion = r.redact(_raw("on_tool_start", "fetch_notion_page", {"input": {"page_id": "abc-secret"}}, node="tools"))

    _assert_clean(web)
    _assert_clean(notion)
    assert web.data == {"input": {"query": "psp"}}
    assert notion.data == {}
    assert "abc-secret" not in repr(notion)


def test_tool_end_carries_only_status_and_tool_call_id():
    r = EventRedactor()
    ok = r.redact(_raw("on_tool_end", "web_search", {"output": ToolMessage(content=f"<<TOOL_CONTENT>>\n{SECRET}\n<</TOOL_CONTENT>>", tool_call_id="c1", name="web_search"), "input": {"query": "psp"}}, node="tools"))
    wrapped_failure = r.redact(_raw("on_tool_end", "web_search", {"output": ToolMessage(content="<<TOOL_CONTENT>>\n(falha ao buscar na web: timeout)\n<</TOOL_CONTENT>>", tool_call_id="c2", name="web_search")}, node="tools"))
    status_error = r.redact(_raw("on_tool_end", "web_search", {"output": ToolMessage(content="Error: boom", tool_call_id="c3", name="web_search", status="error")}, node="tools"))
    raised = r.redact(_raw("on_tool_error", "web_search", {"error": RuntimeError(SECRET), "tool_call_id": "c4", "input": {"query": "psp"}}, node="tools"))

    for ev in (ok, wrapped_failure, status_error, raised):
        _assert_clean(ev)
    assert ok.data == {"output": {"status": "ok", "tool_call_id": "c1"}}
    assert wrapped_failure.data == {"output": {"status": "error", "tool_call_id": "c2"}}
    assert status_error.data == {"output": {"status": "error", "tool_call_id": "c3"}}
    assert raised.event == "on_tool_error" and raised.data == {"output": {"status": "error", "tool_call_id": "c4"}}


def test_tool_events_outside_the_tools_node_are_dropped():
    assert EventRedactor().redact(_raw("on_tool_start", "web_search", {"input": {}}, node="answer")) is None


def test_malformed_updates_payload_and_non_toolmessage_output_fail_closed():
    r = EventRedactor()
    assert r.redact(_raw("on_chain_stream", ROOT_NAME, {"chunk": ("updates", [SECRET])}, root=True)) is None
    weird = r.redact(_raw("on_tool_end", "web_search", {"output": {"raw": SECRET}}, node="tools"))
    assert weird.data == {"output": {"status": "error", "tool_call_id": None}}
    assert SECRET not in repr(weird.data)
