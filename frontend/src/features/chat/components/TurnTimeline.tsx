import type { ActivityItem } from "../../../hooks/useAskStream";
import { stepLabel, toolLabel } from "../timelineLabels";
import styles from "../ChatPage.module.css";

type State = "running" | "done" | "error";

function stateOf(item: ActivityItem): State {
  if (item.kind === "step") return item.status === "done" ? "done" : "running";
  if (item.status === "error") return "error";
  if (item.status === "ok") return "done";
  return "running";
}

/** Linha do tempo do turno (ADR-0019). Só existe enquanto o turno roda: o
 * ChatPage a monta do run_started até done/error. Sem atividade ainda (a fase 1
 * do backend não devolveu nada), mostra os três pontos de espera. */
export function TurnTimeline({ activity }: { activity: ActivityItem[] }) {
  if (activity.length === 0) {
    return (
      <div className={styles.thinking} role="status" aria-label="Pensando">
        <span /><span /><span />
      </div>
    );
  }
  return (
    <ol className={styles.timeline} aria-live="polite" aria-label="Andamento da resposta">
      {activity.map((item, i) => {
        const state = stateOf(item);
        const label = item.kind === "step" ? stepLabel(item.name, item.detail) : toolLabel(item.name, item.args);
        const key = item.kind === "tool" ? `tool-${item.id}` : `step-${item.name}-${i}`;
        return (
          <li key={key} className={styles.timelineItem} data-state={state}>
            <span className={styles.timelineDot} aria-hidden="true" />
            <span className={styles.timelineLabel}>{label}</span>
            {state === "error" && <span className={styles.timelineTag}>falhou</span>}
          </li>
        );
      })}
    </ol>
  );
}
