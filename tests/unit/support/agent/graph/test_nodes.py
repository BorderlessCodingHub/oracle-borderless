"""Cada nó isolado, com dependências fakes. Antes gate e retrieval estavam
soldados dentro de AnswerQuestionAction e não podiam ser testados sozinhos."""

import asyncio

import pytest

from src.support.agent.graph.nodes import gate_node
from src.support.agent.ports import TurnDependencies, TurnSignals


class _FakeStructuredModel:
    """Imita o retorno de model.with_structured_output(...)."""

    def __init__(self, output=None, raises=None, delay=0.0):
        self._output = output
        self._raises = raises
        self._delay = delay
        self.prompt = None

    async def ainvoke(self, messages):
        self.prompt = messages
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return self._output


def _config(signals, model, deps=None):
    return {"configurable": {"signals": signals, "deps": deps, "gate_model": model}}


@pytest.mark.asyncio
async def test_a_substantive_question_asks_for_retrieval_with_a_rewritten_query():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=True, search_query="renovação de PSP"))

    out = await gate_node(
        {"question": "e as renovações?", "history": []}, _config(signals, model)
    )

    assert out["retrieve"] is True
    assert out["search_query"] == "renovação de PSP"
    assert out["degraded"] is False
    assert signals.gate_retrieve is True
    assert signals.gate_search_query == "renovação de PSP"


@pytest.mark.asyncio
async def test_a_greeting_skips_retrieval():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=False, search_query=""))

    out = await gate_node({"question": "valeu!", "history": []}, _config(signals, model))

    assert out["retrieve"] is False
    assert out["search_query"] == ""
    assert signals.gate_degraded is False


@pytest.mark.asyncio
async def test_an_empty_rewritten_query_falls_back_to_the_raw_question():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=True, search_query="   "))

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["search_query"] == "o que é PSP?"


@pytest.mark.asyncio
async def test_a_failing_gate_fails_open_and_marks_the_turn_degraded():
    signals = TurnSignals()
    model = _FakeStructuredModel(raises=RuntimeError("provider caiu"))

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["retrieve"] is True
    assert out["search_query"] == "o que é PSP?"
    assert out["degraded"] is True
    assert signals.gate_degraded is True


@pytest.mark.asyncio
async def test_a_slow_gate_times_out_and_fails_open(monkeypatch):
    from src.support.core.settings import settings

    monkeypatch.setattr(settings, "GATE_TIMEOUT_SECONDS", 0.01)
    signals = TurnSignals()
    model = _FakeStructuredModel(output=None, delay=0.5)

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["degraded"] is True
    assert out["retrieve"] is True


@pytest.mark.asyncio
async def test_the_gate_always_records_its_latency():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=False, search_query=""))

    await gate_node({"question": "oi", "history": []}, _config(signals, model))

    assert signals.gate_ms >= 0


# --- retrieve / refuse ---------------------------------------------------

from src.domain.shared.value_objects.citation import Citation  # noqa: E402
from src.support.agent.graph.nodes import refuse_node, retrieve_node  # noqa: E402
from src.support.agent.ports import KnowledgeSnippet  # noqa: E402


def _snippet(text="conteúdo"):
    return KnowledgeSnippet(
        content=text,
        citation=Citation(source_type="notion", title="Doc", url="https://n", snippet=text[:200]),
    )


class _FakeSearch:
    def __init__(self, snippets=None, raises=None):
        self._snippets = snippets or []
        self._raises = raises
        self.query = None
        self.calls = 0

    async def execute(self, query, top_k=None):
        self.calls += 1
        self.query = query
        if self._raises is not None:
            raise self._raises
        return self._snippets


class _FakeSections:
    def __init__(self, sections=None):
        self._sections = sections or ["PSP", "Borderless Tech"]

    async def execute(self):
        return self._sections


class _FakeNearest:
    def __init__(self, distance=0.61, raises=None):
        self._distance = distance
        self._raises = raises

    async def execute(self, query):
        if self._raises is not None:
            raise self._raises
        return self._distance


def _deps(search=None, sections=None, nearest=None):
    from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply

    return TurnDependencies(
        search=search or _FakeSearch(),
        sections=sections or _FakeSections(),
        refusal=build_out_of_scope_reply,
        nearest=nearest,
    )


@pytest.mark.asyncio
async def test_retrieval_uses_the_query_the_gate_rewrote():
    search = _FakeSearch([_snippet()])
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=search)}}

    out = await retrieve_node({"search_query": "renovação de PSP"}, config)

    assert search.query == "renovação de PSP"
    assert len(out["knowledge"]) == 1


@pytest.mark.asyncio
async def test_retrieval_records_its_signal():
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=_FakeSearch([_snippet(), _snippet()]))}}

    await retrieve_node({"search_query": "q"}, config)

    assert signals.retrieval_ran is True
    assert signals.retrieval_kept == 2
    assert signals.retrieval_ms is not None
    assert signals.retrieval_top_k > 0
    assert signals.retrieval_threshold > 0


@pytest.mark.asyncio
async def test_the_refusal_is_deterministic_and_calls_no_model():
    from src.domain.conversations.services.out_of_scope_reply import OUT_OF_SCOPE_OPENING_PT

    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps()}}

    out = await refuse_node({"question": "quanto custa um carro?", "search_query": "carro"}, config)

    assert out["answer"].startswith(OUT_OF_SCOPE_OPENING_PT)
    assert out["citations"] == []
    assert out["outcome"] == "refusal"
    assert signals.outcome == "refusal"


@pytest.mark.asyncio
async def test_the_refusal_records_the_nearest_distance_for_the_trace():
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(nearest=_FakeNearest(0.61))}}

    await refuse_node({"question": "q", "search_query": "q"}, config)

    assert signals.retrieval_best_distance == 0.61


@pytest.mark.asyncio
async def test_a_failing_distance_probe_never_costs_the_user_the_refusal():
    """Observabilidade não derruba turno: sem distância é melhor que sem recusa."""
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(nearest=_FakeNearest(raises=RuntimeError("pgvector fora")))}}

    out = await refuse_node({"question": "q", "search_query": "q"}, config)

    assert out["outcome"] == "refusal"
    assert signals.retrieval_best_distance is None
