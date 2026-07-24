import json
import logging
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
        conversation_id, stream = await action.execute(
            data.question, data.conversation_id, user_email
        )

        captured: dict = {"text": "", "citations": []}

        async def event_source() -> AsyncIterator[str]:
            yield _sse("conversation", {"id": str(conversation_id)})
            failed = False
            try:
                async for chunk in stream:
                    if chunk.type == "text":
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
                yield _sse("error", {"message": "erro ao gerar a resposta"})

            # Persiste a resposta só quando o stream terminou com sucesso e há texto.
            if not failed and captured["text"]:
                try:
                    await _persist_assistant(
                        conversation_id, captured["text"], captured["citations"]
                    )
                except Exception:
                    logger.exception("falha ao persistir a resposta do oráculo")

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


async def _persist_assistant(conversation_id: UUID, content: str, citations: list) -> None:
    async def _work() -> None:
        await AppendAssistantMessageAction().execute(conversation_id, content, citations)

    await run_in_async_session(_work)
