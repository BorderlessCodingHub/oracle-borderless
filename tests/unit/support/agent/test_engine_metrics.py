"""O engine preenche TurnMetrics sem mudar o contrato SSE."""

import pytest

from src.support.agent.ports import TurnMetrics


def test_turn_metrics_starts_zeroed():
    m = TurnMetrics()
    assert m.tool_calls == 0
    assert m.input_tokens is None
    assert m.output_tokens is None


@pytest.mark.asyncio
async def test_stream_answer_accepts_metrics_and_counts_no_tool_call_without_tools():
    from pydantic_ai.models.test import TestModel  # modelo de teste do pydantic_ai

    from src.support.agent.oracle_engine import OracleEngine

    metrics = TurnMetrics()
    engine = OracleEngine(model=TestModel(), enable_tools=False)

    chunks = [c async for c in engine.stream_answer("pergunta", [], [], metrics=metrics)]

    assert any(c.type == "text" for c in chunks)
    assert metrics.tool_calls == 0


@pytest.mark.asyncio
async def test_stream_answer_without_metrics_still_works():
    """Parâmetro é opcional: nenhum chamador existente muda."""
    from pydantic_ai.models.test import TestModel

    from src.support.agent.oracle_engine import OracleEngine

    engine = OracleEngine(model=TestModel(), enable_tools=False)
    chunks = [c async for c in engine.stream_answer("pergunta", [], [])]
    assert any(c.type == "sources" for c in chunks)
