import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi.responses import StreamingResponse

from src.app.api.requests.stream_events_request import StreamEventsRequest
from src.app.api.responses.conversation_responses import (
    ConversationDetailResponse,
    ConversationSummaryResponse,
)
from src.app.api.streaming.stream_event_encoder import CONTENT_TYPE, encode, error_event
from src.domain.conversations.actions.append_assistant_message_action import (
    AppendAssistantMessageAction,
)
from src.domain.conversations.actions.get_conversation_action import GetConversationAction
from src.domain.conversations.actions.list_conversations_action import ListConversationsAction
from src.domain.conversations.actions.open_turn_action import OpenTurnAction
from src.domain.conversations.actions.run_turn_action import RunTurnAction
from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.graph import get_turn_graph_runner
from src.support.agent.ports import GraphEvent, citations_of, text_of
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.context import CurrentAsyncSessionContext, CurrentRequestContext
from src.support.core.session_scope import async_session_scope, run_in_async_session
from src.support.observability.langsmith import hash_email

logger = logging.getLogger(__name__)


class ConversationController:
    @staticmethod
    async def ask(data: StreamEventsRequest) -> StreamingResponse:
        """POST /conversations/ask — StreamEvents (ADR-0021) em três escopos de sessão (ADR-0020).

        Body são os parâmetros de `astream_events(input, config)`; resposta é a
        sequência de `StreamEvent` redigidos, um por bloco `event:`/`data:`.
        `config.configurable.thread_id` é a conversa, `config.run_id` é o run do
        LangSmith.

        - Escopo 1 (request, sessão do middleware): OpenTurnAction grava conversa
          e pergunta. Tudo que vira status HTTP (401/404/422/500) acontece aqui.
        - Escopo 2 (corpo SSE, `async_session_scope`): RunTurnAction monta os
          deps e o prelúdio do grafo roda — gate, retrieve, recusa — emitindo os
          eventos ao vivo. Fecha na entrada do nó de resposta.
        - Sem sessão: `stream()` — tokens, tools, fim do answer e do raiz.
        - Escopo 3 (`_persist_turn`): trace + resposta do assistente.

        O `on_chain_end` do raiz é RETIDO e só sai depois de persistir: quando o
        cliente o recebe, a conversa já está gravada. Em falha sai
        `on_chain_error` e o `on_chain_end` retido é descartado.

        Duas Actions num endpoint é a exceção registrada no ADR-0020 à regra 5:
        cada uma pertence a um escopo de sessão diferente.
        """
        user_email = CurrentRequestContext.get_user().email
        run_id = data.run_id

        turn = await OpenTurnAction().execute(data.question, data.conversation_id, user_email)
        draft = turn.draft
        # Gravado sempre — coluna barata; o link só aparece na UI quando
        # LANGSMITH_PROJECT_URL está configurado (ver run_url).
        draft.langsmith_run_id = run_id
        thread_id = str(turn.conversation_id)

        graph = get_turn_graph_runner(run_id=run_id, user_hash=hash_email(user_email), thread_id=thread_id)
        # Client HTTP, não captura sessão: pode nascer no request. Quem não pode
        # é SearchKnowledgeBaseAction — nasce em RunTurnAction, dentro do escopo 2.
        embeddings = get_embeddings_client()

        captured: dict = {"text": "", "citations": [], "root_end": None}

        def capture(event: GraphEvent) -> str | None:
            """Guarda texto/fontes para a persistência e serializa o evento.
            O `on_chain_end` do raiz é retido (None) e emitido após persistir."""
            captured["text"] += text_of(event)
            citations = citations_of(event)
            if citations is not None:
                captured["citations"] = citations
            if event.event == "on_chain_end" and event.is_root:
                captured["root_end"] = event
                return None
            return encode(event)

        async def event_source() -> AsyncIterator[str]:
            failed = False
            try:
                async with async_session_scope():
                    run = RunTurnAction(graph, embeddings).execute(turn)
                    async for event in run.prelude():
                        line = capture(event)
                        if line is not None:
                            yield line
                async for event in run.stream():
                    line = capture(event)
                    if line is not None:
                        yield line
            except Exception as exc:
                failed = True
                logger.exception("turno falhou durante /conversations/ask")
                draft.outcome = "error"
                # A mensagem ao usuário continua genérica; só o trace fica
                # informativo. Truncado em 512: é o tamanho da coluna.
                draft.error = f"{type(exc).__name__}: {exc}"[:512]
                yield encode(error_event(run_id, thread_id, "erro ao gerar a resposta"))

            draft.citations_count = len(captured["citations"])
            _absorb_engine_metrics(draft)

            # A resposta só é persistida em sucesso (decisão do M2); o trace é
            # gravado SEMPRE — turno que quebrou é o que mais interessa no trace.
            try:
                await _persist_turn(
                    turn.conversation_id,
                    draft,
                    captured["text"] if (not failed and captured["text"]) else None,
                    captured["citations"],
                )
            except Exception:
                logger.exception("falha ao persistir turno (resposta e/ou trace)")

            # O on_chain_end do raiz só depois de persistir: quando o cliente o
            # recebe, a conversa já está gravada e a sidebar pode recarregar.
            # Depois de on_chain_error não há on_chain_end — é o contrato.
            if not failed and captured["root_end"] is not None:
                yield encode(captured["root_end"])

        return StreamingResponse(event_source(), media_type=CONTENT_TYPE)

    @staticmethod
    async def list() -> list[ConversationSummaryResponse]:
        user_email = CurrentRequestContext.get_user().email
        conversations = await ListConversationsAction().execute(user_email)
        return [ConversationSummaryResponse.from_entity(c) for c in conversations]

    @staticmethod
    async def get(conversation_id: UUID) -> ConversationDetailResponse:
        user_email = CurrentRequestContext.get_user().email
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
    # first_token_ms/engine_ms vêm MEDIDOS do grafo (revisão I2): o nó `answer`
    # carimba a entrada, o runner fecha as contas. Medir daqui somaria gate +
    # retrieval ao primeiro token. `_engine_ran` segue como filtro: a recusa é
    # texto canônico e não entra nas médias do motor. Podem chegar None (turno
    # que quebrou antes do fim do stream); a coluna é nullable.
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
