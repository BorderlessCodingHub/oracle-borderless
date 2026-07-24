import asyncio

import pytest

from src.support.agent.ports import AgentMessage, RetrievalDecision
from src.support.agent.retrieval_gate import RetrievalGate


class _Result:
    def __init__(self, output):
        self.output = output


class _StubAgent:
    """Fake pydantic-ai agent: returns a preset output or raises."""

    def __init__(self, output=None, raises=None):
        self._output = output
        self._raises = raises
        self.prompt = None

    async def run(self, prompt):
        self.prompt = prompt
        if self._raises is not None:
            raise self._raises
        return _Result(self._output)


@pytest.mark.asyncio
async def test_passes_through_a_valid_retrieve_decision():
    agent = _StubAgent(output=RetrievalDecision(retrieve=True, search_query="renovação de PSP"))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("e as renovações?", [AgentMessage("user", "fale do PSP")])

    assert decision.retrieve is True
    assert decision.search_query == "renovação de PSP"


@pytest.mark.asyncio
async def test_passes_through_a_skip_decision():
    agent = _StubAgent(output=RetrievalDecision(retrieve=False, search_query=""))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("valeu!", [])

    assert decision.retrieve is False
    assert decision.search_query == ""


@pytest.mark.asyncio
async def test_fails_open_on_error_retrieving_raw_question():
    agent = _StubAgent(raises=RuntimeError("boom"))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"


@pytest.mark.asyncio
async def test_fails_open_on_timeout():
    agent = _StubAgent(raises=asyncio.TimeoutError())
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"


@pytest.mark.asyncio
async def test_coerces_blank_query_to_raw_question():
    agent = _StubAgent(output=RetrievalDecision(retrieve=True, search_query="   "))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"
