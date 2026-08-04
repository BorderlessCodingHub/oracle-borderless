import { getJSON } from "./client";
import type { EvalReportPayload, OpsOverview, OpsWindow, TurnDetail, TurnSummary } from "../types.ops";

export const getOverview = (w: OpsWindow) => getJSON<OpsOverview>(`/ops/overview?window=${w}`);
export const listTurns = (w: OpsWindow, limit = 50) =>
  getJSON<TurnSummary[]>(`/ops/turns?window=${w}&limit=${limit}`);
export const getTurn = (id: string) => getJSON<TurnDetail>(`/ops/turns/${id}`);
export const getEvalReport = () => getJSON<EvalReportPayload>("/ops/eval");
