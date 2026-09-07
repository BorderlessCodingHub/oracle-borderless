"""`GraphEvent` é o StreamEvent redigido que cruza o port. `text_of` e
`citations_of` são o que o controller e o eval leem sem conhecer a allowlist."""

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import ROOT_NAME, AgentMessage, GraphEvent, KnowledgeSnippet, citations_of, text_of


def _ev(event, name, data, node=None, root=False):
    metadata = {"thread_id": "t1"}
    if node:
        metadata["langgraph_node"] = node
    return GraphEvent(
        event=event, name=name, run_id="r1", tags=[], metadata=metadata,
        parent_ids=[] if root else ["root"], data=data,
    )


def test_node_and_is_root_read_the_langchain_fields():
    assert _ev("on_chain_start", "gate", {}, node="gate").node == "gate"
    assert _ev("on_chain_start", ROOT_NAME, {}, root=True).node is None
    assert _ev("on_chain_start", ROOT_NAME, {}, root=True).is_root is True
    assert _ev("on_chain_start", "gate", {}, node="gate").is_root is False


def test_text_of_reads_answer_tokens():
    ev = _ev("on_chat_model_stream", "ChatAnthropic", {"chunk": {"content": "olá ", "id": "x"}}, node="answer")
    assert text_of(ev) == "olá "


def test_text_of_ignores_tokens_from_other_nodes_and_empty_chunks():
    assert text_of(_ev("on_chat_model_stream", "m", {"chunk": {"content": "x"}}, node="gate")) == ""
    assert text_of(_ev("on_chat_model_stream", "m", {"chunk": {}}, node="answer")) == ""


def test_text_of_reads_the_refusal_from_the_updates_chunk_of_the_root():
    ev = _ev("on_chain_stream", ROOT_NAME, {"chunk": ["updates", {"refuse": {"answer": "Não encontrei.", "citations": []}}]}, root=True)
    assert text_of(ev) == "Não encontrei."


def test_text_of_ignores_values_chunks_and_other_updates():
    assert text_of(_ev("on_chain_stream", ROOT_NAME, {"chunk": ["values", {"answer": "Não encontrei."}]}, root=True)) == ""
    assert text_of(_ev("on_chain_stream", ROOT_NAME, {"chunk": ["updates", {"gate": {"retrieve": True}}]}, root=True)) == ""
    assert text_of(_ev("on_chain_end", "refuse", {"output": {"answer": "Não encontrei."}}, node="refuse")) == ""


def test_citations_of_reads_only_the_root_chain_end():
    c = Citation("notion", "Doc", "https://n/a", "trecho")
    root_end = _ev("on_chain_end", ROOT_NAME, {"output": {"outcome": "answer", "citations": [c]}}, root=True)
    node_end = _ev("on_chain_end", "answer", {"output": {"citations": [c]}}, node="answer")

    assert citations_of(root_end) == [c]
    assert citations_of(node_end) is None
    assert citations_of(_ev("on_chain_end", ROOT_NAME, {"output": {"outcome": "refusal"}}, root=True)) == []


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
