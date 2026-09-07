"""Fake de chat model que É um BaseChatModel: strema por callbacks, então
`ainvoke` dentro de `astream_events` produz `on_chat_model_stream` como
Anthropic/OpenAI fazem. Os fakes antigos (objetos soltos com `ainvoke`) não
emitiam evento nenhum — com o ADR-0021 o texto não chegaria ao fio."""

import asyncio
import json
from typing import Any, AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    replies: list[AIMessage]
    delay: float = 0.0
    released: Any = None  # asyncio.Event | None — espera antes de responder
    explode: str | None = None  # mensagem do RuntimeError, se deve quebrar
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _next(self) -> AIMessage:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.explode:
            raise RuntimeError(self.explode)
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # `ainvoke` FORA de astream_events (sem handler de streaming) cai aqui;
        # tem que honrar released/delay/explode como o _astream.
        await self._gate()
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    async def _gate(self) -> None:
        if self.released is not None:
            await self.released.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.explode:
            raise RuntimeError(self.explode)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        await self._gate()
        message = self._next()
        if message.tool_calls:
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": tc["name"], "args": json.dumps(tc["args"]), "id": tc["id"], "index": i, "type": "tool_call_chunk"}
                        for i, tc in enumerate(message.tool_calls)
                    ],
                )
            )
            if run_manager:
                await run_manager.on_llm_new_token("", chunk=chunk)
            yield chunk
            return
        words = message.content.split(" ")
        for i, word in enumerate(words):
            token = word if i == len(words) - 1 else word + " "
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                await run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk
