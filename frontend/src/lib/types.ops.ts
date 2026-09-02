/**
 * Espelho dos responses de `/ops` (src/app/api/responses/ops_responses.py) e do
 * report gravado pelo harness de eval (evals/report.py). Mudou lá, muda aqui.
 */

export type OpsWindow = "24h" | "7d" | "all";

export interface KnowledgeCounts {
  documents_active: number;
  documents_archived: number;
  chunks: number;
  sections: string[];
}

export interface SyncStatus {
  job_name: string | null;
  status: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface TraceSummary {
  turns: number;
  gate_retrieve: number;
  gate_skip: number;
  gate_degraded: number;
  answers: number;
  refusals: number;
  errors: number;
  avg_first_token_ms: number | null;
  max_first_token_ms: number | null;
  avg_engine_ms: number | null;
  max_engine_ms: number | null;
  avg_retrieval_kept: number | null;
  avg_best_distance: number | null;
}

export interface OpsOverview {
  window: string;
  knowledge: KnowledgeCounts;
  sync: SyncStatus;
  traces: TraceSummary;
  rag_top_k: number;
  rag_max_distance: number;
}

/** `TurnSummaryResponse` — sem `user_email` e sem `message_id`, de propósito. */
export interface TurnSummary {
  id: string;
  created_at: string;
  question: string;
  gate_retrieve: boolean;
  gate_degraded: boolean;
  retrieval_kept: number;
  retrieval_best_distance: number | null;
  outcome: string;
  first_token_ms: number | null;
  engine_ms: number | null;
  citations_count: number;
  tool_calls: number;
}

export interface TurnDetail extends TurnSummary {
  conversation_id: string;
  gate_search_query: string | null;
  gate_ms: number;
  retrieval_ran: boolean;
  retrieval_top_k: number;
  retrieval_threshold: number;
  retrieval_ms: number | null;
  history_messages: number;
  history_tokens_est: number;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string | null;
  langsmith_url: string | null;
}

/** Uma métrica agregada do report — `evals/report.py::_report_dict`. */
export interface EvalMetric {
  metric: string;
  mean: number;
  threshold: number;
  n: number;
  passed: boolean;
}

export interface EvalCaseBreach {
  case_id: string;
  metric: string;
  score: number;
}

export interface EvalHardFailure extends EvalCaseBreach {
  category: string;
}

export interface EvalRun {
  ran_at: string;
  passed: boolean;
  metrics: EvalMetric[];
  below_floor: EvalCaseBreach[];
  hard_failures: EvalHardFailure[];
  cases: {
    case_id: string;
    category: string;
    scores: Record<string, { score: number; reason: string }>;
  }[];
}

export interface EvalReportPayload {
  status: "ok" | "no_runs";
  report: EvalRun | null;
  history: EvalRun[];
}
