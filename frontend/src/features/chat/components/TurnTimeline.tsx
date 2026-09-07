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

/** Linha do tempo do turno (ADR-0019/0020). Só existe enquanto o turno roda: o
 * ChatPage a monta do run_started até done/error. Sem atividade ainda, a lista
 * fica vazia com a altura de uma linha reservada (CSS) e `aria-busy` — o
 * primeiro passo chega no round-trip HTTP, não há mais indicador de espera. */
export function TurnTimeline({ activity }: { activity: ActivityItem[] }) {
  return (
    <ol
      className={styles.timeline}
      aria-live="polite"
      aria-busy={activity.length === 0}
      aria-label="Andamento da resposta"
    >
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
