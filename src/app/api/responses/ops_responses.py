from typing import Literal

from pydantic import BaseModel

from src.domain.observability.dtos.ops_overview import OpsOverview
from src.domain.observability.entities.turn_trace import TurnTrace
from src.support.observability.langsmith import run_url

Window = Literal["24h", "7d", "all"]


class KnowledgeCountsResponse(BaseModel):
    documents_active: int
    documents_archived: int
    chunks: int
    sections: list[str]


class SyncStatusResponse(BaseModel):
    job_name: str | None
    status: str | None
    started_at: str | None
    finished_at: str | None
    error: str | None


class TraceSummaryResponse(BaseModel):
    turns: int
    gate_retrieve: int
    gate_skip: int
    gate_degraded: int
    answers: int
    refusals: int
    errors: int
    avg_first_token_ms: float | None
    max_first_token_ms: int | None
    avg_engine_ms: float | None
    max_engine_ms: int | None
    avg_retrieval_kept: float | None
    avg_best_distance: float | None


class OpsOverviewResponse(BaseModel):
    window: str
    knowledge: KnowledgeCountsResponse
    sync: SyncStatusResponse
    traces: TraceSummaryResponse
    rag_top_k: int
    rag_max_distance: float

    @classmethod
    def from_dto(cls, dto: OpsOverview) -> "OpsOverviewResponse":
        return cls(
            window=dto.window,
            knowledge=KnowledgeCountsResponse(**vars(dto.knowledge)),
            sync=SyncStatusResponse(**vars(dto.sync)),
            traces=TraceSummaryResponse(**vars(dto.traces)),
            rag_top_k=dto.rag_top_k,
            rag_max_distance=dto.rag_max_distance,
        )


# TurnSummaryResponse/TurnDetailResponse omitem, de propósito, dois campos que
# existem na Entity TurnTrace:
#
# - `user_email`: a página de ops está aberta hoje (require_admin é no-op, por
#   decisão da dona do produto). Expor o e-mail de quem fez cada pergunta para
#   qualquer um com a URL seria vazamento de dado pessoal. Quando a auth de
#   admin existir, isso pode ser revisto — mas é decisão de então, não de agora.
# - `message_id`: hoje nunca é preenchido (nem a Action nem o controller de
#   conversations o atribuem — o retorno de AppendAssistantMessageAction é
#   descartado), então a coluna é sempre NULL. Expor um campo sempre nulo só
#   geraria dúvida na tela.
class TurnSummaryResponse(BaseModel):
    id: str
    created_at: str
    question: str
    gate_retrieve: bool
    gate_degraded: bool
    retrieval_kept: int
    retrieval_best_distance: float | None
    outcome: str
    first_token_ms: int | None
    engine_ms: int | None
    citations_count: int
    tool_calls: int

    @classmethod
    def from_entity(cls, t: TurnTrace) -> "TurnSummaryResponse":
        return cls(
            id=str(t.uuid),
            created_at=t.created_at.isoformat(),
            question=t.question,
            gate_retrieve=t.gate_retrieve,
            gate_degraded=t.gate_degraded,
            retrieval_kept=t.retrieval_kept,
            retrieval_best_distance=t.retrieval_best_distance,
            outcome=t.outcome,
            first_token_ms=t.first_token_ms,
            engine_ms=t.engine_ms,
            citations_count=t.citations_count,
            tool_calls=t.tool_calls,
        )


class TurnDetailResponse(TurnSummaryResponse):
    conversation_id: str
    gate_search_query: str | None
    gate_ms: int
    retrieval_ran: bool
    retrieval_top_k: int
    retrieval_threshold: float
    retrieval_ms: int | None
    history_messages: int
    history_tokens_est: int
    input_tokens: int | None
    output_tokens: int | None
    error: str | None
    langsmith_url: str | None

    @classmethod
    def from_entity(cls, t: TurnTrace) -> "TurnDetailResponse":
        base = TurnSummaryResponse.from_entity(t)
        return cls(
            **base.model_dump(),
            conversation_id=str(t.conversation_id),
            gate_search_query=t.gate_search_query,
            gate_ms=t.gate_ms,
            retrieval_ran=t.retrieval_ran,
            retrieval_top_k=t.retrieval_top_k,
            retrieval_threshold=t.retrieval_threshold,
            retrieval_ms=t.retrieval_ms,
            history_messages=t.history_messages,
            history_tokens_est=t.history_tokens_est,
            input_tokens=t.input_tokens,
            output_tokens=t.output_tokens,
            error=t.error,
            langsmith_url=run_url(t.langsmith_run_id),
        )


class EvalReportResponse(BaseModel):
    """Último run do judge eval, ou estado vazio quando nunca rodou.

    `report`/`history` ficam como dict/list[dict] de propósito: a forma
    interna do report é definida pelo harness em `evals/report.py`, e
    espelhá-la campo a campo aqui criaria um segundo lugar para desatualizar.
    Este schema tranca só o envelope (`status` e a presença das duas chaves) —
    o que o frontend precisa para decidir entre estado vazio e painel
    preenchido.
    """

    status: str  # "ok" | "no_runs"
    report: dict | None
    history: list[dict]
