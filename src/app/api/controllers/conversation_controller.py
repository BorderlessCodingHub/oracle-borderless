import json
import logging
import time
from typing import AsyncIterator
from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse

from src.app.api.requests.ask_question_request import AskQuestionRequest
from src.app.api.responses.conversation_responses import (
    ConversationDetailResponse,
    ConversationSummaryResponse,
)
from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.actions.append_assistant_message_action import (
    AppendAssistantMessageAction,
)
from src.domain.conversations.actions.get_conversation_action import GetConversationAction
from src.domain.conversations.actions.list_conversations_action import ListConversationsAction
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction
from src.support.agent.oracle_engine import get_oracle_engine
from src.support.agent.retrieval_gate import get_retrieval_gate
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.session_scope import run_in_async_session

logger = logging.getLogger(__name__)

_USER_EMAIL_HEADER = "cf-access-authenticated-user-email"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _citation_payload(c) -> dict:
    return {"source_type": c.source_type, "title": c.title, "url": c.url, "snippet": c.snippet}


class ConversationController:
    @staticmethod
    async def ask(request: Request, data: AskQuestionRequest) -> StreamingResponse:
        user_email = request.headers.get(_USER_EMAIL_HEADER)
        search = SearchKnowledgeBaseAction(embeddings=get_embeddings_client())
        action = AnswerQuestionAction(
            engine=get_oracle_engine(), search=search, gate=get_retrieval_gate()
        )

        # Conversa + user message são gravadas aqui (sessão do request viva).
        conversation_id, stream, draft = await action.execute(
            data.question, data.conversation_id, user_email
        )

        captured: dict = {"text": "", "citations": []}

        async def event_source() -> AsyncIterator[str]:
            yield _sse("conversation", {"id": str(conversation_id)})
            failed = False
            engine_started = time.monotonic()
            try:
                async for chunk in stream:
                    if chunk.type == "text":
                        if draft.first_token_ms is None:
                            draft.first_token_ms = int(
                                (time.monotonic() - engine_started) * 1000
                            )
                            draft.record("first_token")
                        captured["text"] += chunk.text
                        yield _sse("token", {"text": chunk.text})
                    elif chunk.type == "sources":
                        captured["citations"] = chunk.citations
                        yield _sse(
                            "sources",
                            {"citations": [_citation_payload(c) for c in chunk.citations]},
                        )
            except Exception:
                failed = True
                logger.exception("stream falhou durante /conversations/ask")
                draft.outcome = "error"
                draft.error = "erro ao gerar a resposta"
                yield _sse("error", {"message": "erro ao gerar a resposta"})

            draft.engine_ms = int((time.monotonic() - engine_started) * 1000)
            draft.citations_count = len(captured["citations"])
            _absorb_engine_metrics(draft)
            draft.record("turn_end", outcome=draft.outcome)

            # A resposta só é persistida em sucesso (decisão do M2); o trace é
            # gravado SEMPRE — turno que quebrou é o que mais interessa no trace.
            try:
                await _persist_turn(
                    conversation_id,
                    draft,
                    captured["text"] if (not failed and captured["text"]) else None,
                    captured["citations"],
                )
            except Exception:
                logger.exception("falha ao persistir turno (resposta e/ou trace)")

            yield _sse("done", {})

        return StreamingResponse(event_source(), media_type="text/event-stream")

    @staticmethod
    async def list(request: Request) -> list[ConversationSummaryResponse]:
        user_email = request.headers.get(_USER_EMAIL_HEADER)
        conversations = await ListConversationsAction().execute(user_email)
        return [ConversationSummaryResponse.from_entity(c) for c in conversations]

    @staticmethod
    async def get(request: Request, conversation_id: UUID) -> ConversationDetailResponse:
        user_email = request.headers.get(_USER_EMAIL_HEADER)
        conversation, messages = await GetConversationAction().execute(
            conversation_id, user_email
        )
        return ConversationDetailResponse.from_entity(conversation, messages)


def _absorb_engine_metrics(draft) -> None:
    metrics = getattr(draft, "engine_metrics", None)
    if metrics is None:
        return  # caminho de recusa: não houve engine
    draft.tool_calls = metrics.tool_calls
    draft.input_tokens = metrics.input_tokens
    draft.output_tokens = metrics.output_tokens


async def _persist_turn(conversation_id: UUID, draft, content: str | None, citations: list) -> None:
    """Uma sessão própria para as duas escritas pós-stream."""

    async def _work() -> None:
        if content:
            await AppendAssistantMessageAction().execute(conversation_id, content, citations)
        try:
            await RecordTurnTraceAction().execute(conversation_id, draft)
        except Exception:
            # Invariante da spec: observabilidade não pode custar a resposta.
            logger.exception("falha ao gravar o trace do turno")

    await run_in_async_session(_work)
