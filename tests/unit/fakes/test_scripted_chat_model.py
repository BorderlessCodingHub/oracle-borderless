"""O fake de modelo precisa ser um BaseChatModel de verdade: dentro de
`astream_events`, `ainvoke` só produz `on_chat_model_stream` quando o modelo
strema via callbacks. Um objeto solto com `ainvoke` não emite evento nenhum."""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from tests.fakes.scripted_chat_model import ScriptedChatModel


@pytest.mark.asyncio
async def test_ainvoke_inside_astream_events_streams_word_by_word():
    model = ScriptedChatModel(replies=[AIMessage(content="PSP é um programa")])

    tokens = []
    async for ev in model.astream_events("oi", version="v2"):
        if ev["event"] == "on_chat_model_stream":
            tokens.append(ev["data"]["chunk"].content)

    assert "".join(tokens) == "PSP é um programa"
    assert len([t for t in tokens if t]) == 4


@pytest.mark.asyncio
async def test_replies_are_consumed_in_order_and_the_last_one_repeats():
    model = ScriptedChatModel(replies=[AIMessage(content="um"), AIMessage(content="dois")])

    assert (await model.ainvoke("a")).content == "um"
    assert (await model.ainvoke("b")).content == "dois"
    assert (await model.ainvoke("c")).content == "dois"
    assert model.calls == 3


@pytest.mark.asyncio
async def test_a_tool_calls_only_reply_streams_one_chunk_with_tool_call_chunks():
    model = ScriptedChatModel(replies=[AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "psp"}, "id": "call-1"}])])

    chunks = [ev["data"]["chunk"] async for ev in model.astream_events("oi", version="v2") if ev["event"] == "on_chat_model_stream"]
    with_calls = [c for c in chunks if c.tool_call_chunks]

    assert len(with_calls) == 1
    assert with_calls[0].tool_call_chunks[0]["name"] == "web_search"
    assert with_calls[0].tool_call_chunks[0]["id"] == "call-1"
    result = await model.ainvoke("oi")
    assert result.tool_calls[0]["id"] == "call-1"


@pytest.mark.asyncio
async def test_released_blocks_until_set_and_explode_raises():
    released = asyncio.Event()
    blocking = ScriptedChatModel(replies=[AIMessage(content="x")], released=released)
    task = asyncio.create_task(blocking.ainvoke("oi"))
    await asyncio.sleep(0.01)
    assert not task.done()
    released.set()
    assert (await task).content == "x"

    exploding = ScriptedChatModel(replies=[AIMessage(content="x")], explode="provider caiu antes do primeiro token")
    with pytest.raises(RuntimeError, match="provider caiu"):
        await exploding.ainvoke("oi")
