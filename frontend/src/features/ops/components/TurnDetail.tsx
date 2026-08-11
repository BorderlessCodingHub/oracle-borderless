import type { TurnDetail as Detail } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function TurnDetail({ turn }: { turn: Detail | null }) {
  if (!turn) return <p className={styles.muted}>Selecione um turno para ver a sequência.</p>;
  return (
    <div className={styles.sequence}>
      <p className={styles.muted}>
        {turn.question} · limiar {turn.retrieval_threshold} · top-k {turn.retrieval_top_k}
        {turn.retrieval_best_distance !== null && ` · mais próximo ${turn.retrieval_best_distance.toFixed(3)}`}
      </p>
      <ol className={styles.steps}>
        {turn.events.map((e, i) => (
          <li key={`${e.step}-${i}`}>
            <span className={styles.stepAt}>{e.at_ms}ms</span>
            <span className={styles.stepName}>{e.step}</span>
            <span className={styles.stepDetail}>
              {Object.entries(e.detail ?? {})
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(" · ")}
            </span>
          </li>
        ))}
      </ol>
      {turn.error && <p className={styles.error}>{turn.error}</p>}
    </div>
  );
}
