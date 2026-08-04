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


@pytest.mark.asyncio
async def test_stream_answer_fills_token_counts_from_usage():
    """Regressão: `StreamedRunResult.usage` é property em pydantic-ai 2.4.0,
    não método. Se `_fill_usage` voltar a chamar `result.usage()`, o
    `TestModel` (que expõe o mesmo `StreamedRunResult`) levanta o mesmo
    `TypeError` que o motor real levanta contra o modelo real — o `except`
    engole a falha e este teste falharia ao ver `input_tokens`/`output_tokens`
    None."""
    from pydantic_ai.models.test import TestModel

    from src.support.agent.oracle_engine import OracleEngine

    metrics = TurnMetrics()
    engine = OracleEngine(model=TestModel(), enable_tools=False)

    _ = [c async for c in engine.stream_answer("pergunta", [], [], metrics=metrics)]

    assert isinstance(metrics.input_tokens, int) and metrics.input_tokens > 0
    assert isinstance(metrics.output_tokens, int) and metrics.output_tokens > 0


@pytest.mark.asyncio
async def test_stream_answer_counts_tool_calls_when_tools_are_invoked():
    """Regressão: prende que `metrics.tool_calls` incrementa de verdade nos
    dois closures de tool (`web_search`/`fetch_notion_page`), não só que o
    contador fica em 0 quando nenhuma tool está registrada.

    `TestModel(call_tools="all")` (default do pydantic-ai) chama toda tool
    registrada no agent — aqui isso dispara as duas, contra Tavily/Notion
    reais sem chave de API configurada nesses testes, e elas falham. Isso é
    esperado e não quebra o teste: os closures do engine capturam a exceção
    da tool e devolvem conteúdo de erro ao agente (comportamento existente,
    não desta task) — o que importa é que `metrics.tool_calls` incrementou
    ANTES da tentativa, então mesmo a tool falhando conta como chamada."""
    from pydantic_ai.models.test import TestModel

    from src.domain.shared.value_objects.citation import Citation
    from src.support.agent.oracle_engine import OracleEngine
    from src.support.agent.ports import KnowledgeSnippet

    metrics = TurnMetrics()
    engine = OracleEngine(model=TestModel(), enable_tools=True)
    knowledge = [KnowledgeSnippet("trecho", Citation("notion", "Doc", "u", "s", "pid"))]

    _ = [c async for c in engine.stream_answer("pergunta", [], knowledge, metrics=metrics)]

    assert metrics.tool_calls == 2  # web_search + fetch_notion_page
