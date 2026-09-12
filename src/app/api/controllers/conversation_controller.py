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
from src.domain.lessons.actions.check_lesson_access_action import (
    CheckLessonAccessAction,
    LessonAccessDeniedError,
)
from src.domain.lessons.entities.lesson import Lesson
from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.domain.observability.services.mentor_trace import apply_mentor_signals
from src.domain.users.actions.resolve_bearer_action import SOURCE_PLATFORM_BEARER
from src.support.agent.graph import get_turn_graph_runner
from src.support.agent.navigation_catalog import NavigationCatalog
from src.support.agent.ports import GraphEvent, citations_of, navigation_of, text_of
from src.support.clients.borderless.borderless_lesson_access_client import (
    BorderlessLessonAccessClient,
)
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.context import CurrentAsyncSessionContext, CurrentRequestContext
from src.support.core.exceptions import DomainError, NotFoundError
from src.support.core.session_scope import async_session_scope, run_in_async_session
from src.support.core.settings import settings
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

        - Escopo 1 (request, sessão do middleware): mode="mentor" checa o
          entitlement (CheckLessonAccessAction — 400 sem lesson_id, 403 sem
          acesso, fail-closed) ANTES de tudo, e OpenTurnAction grava conversa
          e pergunta. Tudo que vira status HTTP (400/401/403/404/422/500)
          acontece aqui.
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
        user = CurrentRequestContext.get_user()
        user_email = user.email
        run_id = data.run_id

        # Mentor (Task 4): entitlement fail-closed, ANTES de qualquer chamada de
        # modelo e ainda na sessão do middleware (a LessonRepository precisa
        # dela) — 400 sem lesson_id, 403 sem acesso (LessonAccessDeniedError,
        # mapeado em exception_handlers.py).
        lesson: Lesson | None = None
        if data.mode == "mentor":
            # I2 (ruling C7): kill switch de verdade. Antes de qualquer outra
            # checagem — inclusive antes do 400 de lesson_id ausente — porque
            # com o mentor desligado nem faz sentido diferenciar os dois erros
            # de entrada; a feature simplesmente não existe.
            if not settings.MENTOR_ENABLED:
                raise NotFoundError("mentor desabilitado")
            if not data.lesson_id:
                raise DomainError("mode mentor exige input.lesson_id")
            lesson = await CheckLessonAccessAction(access_client=BorderlessLessonAccessClient()).execute(
                bearer=user.platform_access_token, platform_video_id=data.lesson_id
            )

        turn = await OpenTurnAction().execute(
            data.question, data.conversation_id, user_email, mode=data.mode, locale=data.locale,
            lesson_id=lesson.platform_video_id if lesson is not None else None,
        )
        draft = turn.draft
        # Gravado sempre — coluna barata; o link só aparece na UI quando
        # LANGSMITH_PROJECT_URL está configurado (ver run_url).
        draft.langsmith_run_id = run_id
        thread_id = str(turn.conversation_id)

        graph = get_turn_graph_runner(run_id=run_id, user_hash=hash_email(user_email), thread_id=thread_id)
        # Client HTTP, não captura sessão: pode nascer no request. Quem não pode
        # é SearchKnowledgeBaseAction — nasce em RunTurnAction, dentro do escopo 2.
        embeddings = get_embeddings_client()

        extra_config = await _build_extra_config(user, data.mode)
        if lesson is not None:
            extra_config.update(build_mentor_extra_config(lesson))

        captured: dict = {"text": "", "citations": [], "navigation": None, "root_end": None}

        def capture(event: GraphEvent) -> str | None:
            """Guarda texto/fontes/navegação para a persistência e serializa o
            evento. O `on_chain_end` do raiz é retido (None) e emitido após
            persistir."""
            captured["text"] += text_of(event)
            citations = citations_of(event)
            if citations is not None:
                captured["citations"] = citations
            navigation = navigation_of(event)
            if navigation is not None:
                captured["navigation"] = navigation
            if event.event == "on_chain_end" and event.is_root:
                captured["root_end"] = event
                return None
            return encode(event)

        async def event_source() -> AsyncIterator[str]:
            failed = False
            run = None
            try:
                async with async_session_scope():
                    run = RunTurnAction(graph, embeddings).execute(turn, extra_config=extra_config)
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
            finally:
                if run is not None:
                    await run.aclose()

            draft.citations_count = len(captured["citations"])
            finalize_mentor_trace(draft, data.mode, extra_config)

            # A resposta só é persistida em sucesso (decisão do M2); o trace é
            # gravado SEMPRE — turno que quebrou é o que mais interessa no trace.
            try:
                await _persist_turn(
                    turn.conversation_id,
                    draft,
                    captured["text"] if (not failed and captured["text"]) else None,
                    captured["citations"],
                    captured["navigation"],
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


async def _build_extra_config(user, mode: str = "chat") -> dict:
    """Monta o `extra_config` do turno (vira `configurable` do grafo — ADR-0016/
    0021): token e perfil alimentam a tool `navigate_platform` e o prompt de
    navegação. Roda no escopo do request: `NavigationCatalog().describe` é HTTP
    puro, não captura sessão. Um catálogo indisponível não pode derrubar o
    turno — cai para o snapshot embutido. O token NUNCA entra no log.

    R12 (ADR-0022): navegar é capacidade da SESSÃO, não do endpoint. Só o
    cliente embutido na Platform (sessão `platform_bearer`) executa o redirect;
    o SPA do oráculo não sabe navegar, então não recebe a tool, o bloco de
    prompt nem paga a busca do catálogo.

    I3: o mentor liga só `search_lesson` ao modelo (spec §2.1) — nunca
    `navigate_platform` — então um turno `mode == "mentor"` nem busca o
    catálogo ao vivo, mesmo vindo de uma sessão `platform_bearer`. Sem isso
    todo turno mentor pagava um round-trip à borderless-api para um catálogo
    que o grafo nunca usa (ver `model_bound_tools`/`_answer_model(mode="mentor")`).
    """
    navigation_enabled = mode != "mentor" and user.session_source == SOURCE_PLATFORM_BEARER

    catalog_text = None
    if navigation_enabled:
        try:
            catalog_text = await NavigationCatalog().describe(user.platform_access_token)
        except Exception:
            logger.warning("catálogo de navegação indisponível; usando snapshot embutido", exc_info=True)
            catalog_text = NavigationCatalog.snapshot_text()

    return {
        "platform_token": user.platform_access_token,
        "user_profile": {
            "membership": user.membership,
            "seniority": user.seniority,
            "careerStage": user.career_stage,
        },
        "navigation_enabled": navigation_enabled,
        "navigation_catalog_text": catalog_text,
    }


def build_mentor_extra_config(lesson: Lesson) -> dict:
    """`extra_config` do turno mentor (C5): as CINCO chaves que a tool
    `search_lesson` espera em `configurable`. `lesson_id` aqui é o INTERNO
    (`lessons.uuid`) — o escopo da tool; o id da Platform vem à parte em
    `lesson_platform_video_id` (C1: os dois ids nunca se misturam).
    `lesson_distances`/`question_embedding` nascem vazios — a tool os
    preenche em place (`extend`/`[:] =`)."""
    return {
        "lesson_id": lesson.uuid,
        "lesson_distances": [],
        "question_embedding": [],
        "lesson_platform_video_id": lesson.platform_video_id,
        "lesson_program_slug": lesson.program_slug,
    }


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
    draft.intent = s.intent
    draft.navigation_called = s.navigation_called
    draft.navigation_access = s.navigation_access
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


def finalize_mentor_trace(draft: TurnTraceDraft, mode: str, extra_config: dict) -> None:
    """A sequência exata que o corpo SSE roda pós-stream (T5), extraída para
    ser testável sem sessão/HTTP: absorve as métricas do engine PRIMEIRO e só
    DEPOIS — quando o turno é mentor — aplica os sinais do mentor por cima.

    A ORDEM importa: `apply_mentor_signals` sobrescreve de propósito
    `draft.intent`/`draft.retrieval_kept` (o mentor não passa pelo gate/retrieve
    genérico — spec §2.1) com os valores que a tool `search_lesson` preencheu
    em `extra_config`. Se rodasse ANTES de `_absorb_engine_metrics`, o absorb
    reescreveria esses mesmos campos com o que `signals` trouxe do grafo (um
    `intent` de gate que nem rodou, um `retrieval_kept` de RAG genérico que
    também não rodou) — apagando o que o mentor escreveu.

    Sob try/except próprio (ADR-0013): observabilidade nunca derruba a
    persistência da resposta.
    """
    _absorb_engine_metrics(draft)
    if mode == "mentor":
        try:
            apply_mentor_signals(draft, extra_config)
        except Exception:
            logger.exception("falha ao aplicar sinais do mentor no trace")


async def _persist_turn(
    conversation_id: UUID,
    draft: TurnTraceDraft,
    content: str | None,
    citations: list,
    navigation: dict | None = None,
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
                        conversation_id, content, citations, navigation=navigation
                    )
            except Exception:
                logger.exception("falha ao persistir a resposta do oráculo")

    await run_in_async_session(_work)
