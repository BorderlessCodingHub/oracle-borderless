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
