import type { OpsOverview } from "../../lib/types.ops";
import type { MapBox } from "./architectureMap";

const ms = (v: number | null) => (v === null ? "—" : `${Math.round(v)}ms`);

/** Uma linha curta de número para a caixa. `null` = caixa sem métrica. */
export function boxMetric(box: MapBox, o: OpsOverview | null): string | null {
  if (!box.metric || !o) return null;
  const t = o.traces;
  switch (box.metric) {
    case "knowledge":
      return `${o.knowledge.documents_active} ativos · ${o.knowledge.chunks} chunks`;
    case "sync":
      return o.sync.status ? `último: ${o.sync.status}` : "nunca rodou";
    case "recency":
      return t.turns ? `${t.turns} turnos na janela` : "sem turnos";
    case "gate":
      return `${t.gate_retrieve} retrieve · ${t.gate_skip} skip${
        t.gate_degraded ? ` · ${t.gate_degraded} degraded` : ""
      }`;
    case "retrieval":
      return `limiar ${o.rag_max_distance} · top-k ${o.rag_top_k} · média ${
        t.avg_retrieval_kept === null ? "—" : t.avg_retrieval_kept.toFixed(1)
      } aprovados`;
    case "refusals":
      return `${t.refusals} recusas`;
    case "engine":
      return `1º token ${ms(t.avg_first_token_ms)} · total ${ms(t.avg_engine_ms)}`;
    case "turns":
      return `${t.answers} respostas · ${t.errors} erros`;
    default:
      return null;
  }
}
