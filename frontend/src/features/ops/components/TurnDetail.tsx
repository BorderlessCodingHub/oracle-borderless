import type { TurnDetail as Detail } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

export function TurnDetail({ turn }: { turn: Detail | null }) {
  if (!turn) return <p className={styles.muted}>Selecione um turno para ver o detalhe.</p>;
  return (
    <div className={styles.sequence}>
      <p className={styles.muted}>
        {turn.question} · limiar {turn.retrieval_threshold} · top-k {turn.retrieval_top_k}
        {turn.retrieval_best_distance !== null && ` · mais próximo ${turn.retrieval_best_distance.toFixed(3)}`}
      </p>
      {turn.langsmith_url ? (
        <a className={styles.stepName} href={turn.langsmith_url} target="_blank" rel="noreferrer">
          Ver o run completo no LangSmith →
        </a>
      ) : (
        <p className={styles.muted}>Sem trace no LangSmith para este turno.</p>
      )}
      {turn.error && <p className={styles.error}>{turn.error}</p>}
    </div>
  );
}
