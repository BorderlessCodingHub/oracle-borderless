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
from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.graph import get_turn_graph_runner
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.session_scope import run_in_async_session
from src.support.observability.langsmith import hash_email, new_run_id

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
        run_id = new_run_id()
        action = AnswerQuestionAction(
            graph=get_turn_graph_runner(run_id=run_id, user_hash=hash_email(user_email)),
            search=search,
        )

        # Conversa + user message são gravadas aqui (sessão do request viva).
        conversation_id, stream, draft = await action.execute(
            data.question, data.conversation_id, user_email
        )
        # Gravado sempre — coluna barata; o link só aparece na UI quando
        # LANGSMITH_PROJECT_URL está configurado (ver run_url).
        draft.langsmith_run_id = run_id

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
            except Exception as exc:
                failed = True
                logger.exception("stream falhou durante /conversations/ask")
                draft.outcome = "error"
                # A mensagem ao usuário (evento SSE) continua genérica; só o
                # trace fica informativo. Truncado em 512: é o tamanho da coluna.
                draft.error = f"{type(exc).__name__}: {exc}"[:512]
                yield _sse("error", {"message": "erro ao gerar a resposta"})

            draft.citations_count = len(captured["citations"])
            _absorb_engine_metrics(draft)

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


def _engine_ran(draft: TurnTraceDraft) -> bool:
    """Só há "latência do motor" quando um modelo de fato rodou. A recusa é
    texto canônico emitido na hora; contá-la aqui misturaria as duas coisas na
    média que a página de ops mostra."""
    return draft.signals is not None and draft.signals.outcome == "answer"


def _absorb_engine_metrics(draft: TurnTraceDraft) -> None:
    s = draft.signals
    if s is None:
        return
    draft.gate_retrieve = s.gate_retrieve
    draft.gate_search_query = s.gate_search_query
    draft.gate_degraded = s.gate_degraded
    draft.gate_ms = s.gate_ms
    draft.retrieval_ran = s.retrieval_ran
    draft.retrieval_top_k = s.retrieval_top_k
    draft.retrieval_kept = s.retrieval_kept
    draft.retrieval_ms = s.retrieval_ms
    draft.retrieval_best_distance = s.retrieval_best_distance
    draft.retrieval_threshold = s.retrieval_threshold
    draft.tool_calls = s.tool_calls
    draft.input_tokens = s.input_tokens
    draft.output_tokens = s.output_tokens
    # first_token_ms/engine_ms vêm MEDIDOS do grafo (revisão I2). O controller
    # não pode cronometrá-los: com o consumo em duas fases o primeiro token já
    # nasceu durante o `await start()`, antes de este corpo SSE começar a
    # iterar — medir daqui dava ~0 no primeiro token e deixava de fora a fatia
    # dominante do engine_ms. `_engine_ran` segue como filtro: a recusa é texto
    # canônico e não entra nas médias do motor. Podem chegar None (turno que
    # quebrou antes do fim do stream); a coluna é nullable.
    if _engine_ran(draft):
        draft.first_token_ms = s.first_token_ms
        draft.engine_ms = s.engine_ms
    # `outcome` só vem do signals se o controller não o marcou como "error":
    # um turno que quebrou no meio do stream continua sendo erro.
    if draft.outcome != "error":
        draft.outcome = s.outcome


async def _persist_turn(
    conversation_id: UUID, draft: TurnTraceDraft, content: str | None, citations: list
) -> None:
    """Uma sessão própria para as duas escritas pós-stream.

    Cada escrita roda em savepoint próprio (`begin_nested`): um erro de banco
    (ex.: overflow de coluna) aborta só o savepoint dela, não a transação
    inteira — sem isso, a falha ao gravar o trace levaria embora a resposta
    do assistente já persistida (e vice-versa), porque o Postgres marca a
    transação inteira como abortada e o commit final vira ROLLBACK silencioso.
    O trace vai primeiro: é o que mais interessa quando o turno deu errado.
    """

    async def _work() -> None:
        try:
            async with CurrentAsyncSessionContext.get().begin_nested():
                await RecordTurnTraceAction().execute(conversation_id, draft)
        except Exception:
            # Invariante da spec: observabilidade não pode custar a resposta.
            logger.exception("falha ao gravar o trace do turno")

        if content:
            try:
                async with CurrentAsyncSessionContext.get().begin_nested():
                    await AppendAssistantMessageAction().execute(
                        conversation_id, content, citations
                    )
            except Exception:
                logger.exception("falha ao persistir a resposta do oráculo")

    await run_in_async_session(_work)
