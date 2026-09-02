import * as api from "../lib/api/ops";
import type {
  EvalReportPayload,
  OpsOverview,
  OpsWindow,
  TurnDetail,
  TurnSummary,
} from "../lib/types.ops";

const DEMO = import.meta.env.VITE_DEMO_MODE === "true";

// Em modo demo a página tem que abrir sem backend, como o resto do front.
// Números ilustrativos — não vêm de nenhum ambiente real.
const DEMO_OVERVIEW: OpsOverview = {
  window: "24h",
  knowledge: {
    documents_active: 42,
    documents_archived: 520,
    chunks: 261,
    sections: ["Bootcamps", "Mentorias", "Programas"],
  },
  sync: {
    job_name: "SyncKnowledgeBaseJob",
    status: "success",
    started_at: "2026-08-04T03:00:00+00:00",
    finished_at: "2026-08-04T03:04:12+00:00",
    error: null,
  },
  traces: {
    turns: 12,
    gate_retrieve: 9,
    gate_skip: 3,
    gate_degraded: 0,
    answers: 10,
    refusals: 2,
    errors: 0,
    avg_first_token_ms: 820,
    max_first_token_ms: 1640,
    avg_engine_ms: 3120,
    max_engine_ms: 6890,
    avg_retrieval_kept: 3.4,
    avg_best_distance: 0.32,
  },
  rag_top_k: 6,
  rag_max_distance: 0.55,
};

const DEMO_TURNS: TurnSummary[] = [
  {
    id: "demo-turn-1",
    created_at: "2026-08-04T12:31:07+00:00",
    question: "Como funciona o bootcamp de dados?",
    gate_retrieve: true,
    gate_degraded: false,
    retrieval_kept: 4,
    retrieval_best_distance: 0.21,
    outcome: "answer",
    first_token_ms: 760,
    engine_ms: 2980,
    citations_count: 3,
    tool_calls: 1,
  },
  {
    id: "demo-turn-2",
    created_at: "2026-08-04T12:18:44+00:00",
    question: "Qual o salário do time de engenharia?",
    gate_retrieve: true,
    gate_degraded: false,
    retrieval_kept: 0,
    retrieval_best_distance: 0.71,
    outcome: "refusal",
    first_token_ms: null,
    engine_ms: null,
    citations_count: 0,
    tool_calls: 0,
  },
];

const DEMO_DETAILS: Record<string, TurnDetail> = {
  "demo-turn-1": {
    ...DEMO_TURNS[0],
    conversation_id: "demo-conversation-1",
    gate_search_query: "bootcamp de dados formato duração",
    gate_ms: 310,
    retrieval_ran: true,
    retrieval_top_k: 6,
    retrieval_threshold: 0.55,
    retrieval_ms: 88,
    history_messages: 2,
    history_tokens_est: 180,
    input_tokens: 2410,
    output_tokens: 320,
    error: null,
    langsmith_url: "https://smith.langchain.com/o/demo/projects/p/demo/r/demo-turn-1",
  },
  "demo-turn-2": {
    ...DEMO_TURNS[1],
    conversation_id: "demo-conversation-2",
    gate_search_query: "salário time engenharia",
    gate_ms: 290,
    retrieval_ran: true,
    retrieval_top_k: 6,
    retrieval_threshold: 0.55,
    retrieval_ms: 74,
    history_messages: 0,
    history_tokens_est: 0,
    input_tokens: null,
    output_tokens: null,
    error: null,
    langsmith_url: null,
  },
};

const DEMO_EVAL: EvalReportPayload = { status: "no_runs", report: null, history: [] };

export function getOverview(window: OpsWindow): Promise<OpsOverview> {
  if (DEMO) return Promise.resolve({ ...DEMO_OVERVIEW, window });
  return api.getOverview(window);
}

export function listTurns(window: OpsWindow, limit = 50): Promise<TurnSummary[]> {
  if (DEMO) return Promise.resolve(DEMO_TURNS.slice(0, limit));
  return api.listTurns(window, limit);
}

export function getTurn(id: string): Promise<TurnDetail> {
  if (DEMO) {
    const detail = DEMO_DETAILS[id];
    return detail
      ? Promise.resolve(detail)
      : Promise.reject(new Error(`turno ${id} não existe no modo demo`));
  }
  return api.getTurn(id);
}

export function getEvalReport(): Promise<EvalReportPayload> {
  if (DEMO) return Promise.resolve(DEMO_EVAL);
  return api.getEvalReport();
}
