import type { OpsOverview } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

/** O que a base não cobre mas quase cobria. Recusas ordenadas pela distância
 *  do vizinho mais próximo — quanto mais perto do limiar, mais provável que
 *  falte o trecho certo, não o assunto. */
export function KnowledgeGaps({ overview }: { overview: OpsOverview | null }) {
  const gaps = overview?.knowledge_gaps ?? [];
  if (!overview) return null;
  if (gaps.length === 0) {
    return <p className={styles.muted}>Nenhuma recusa com distância medida nesta janela.</p>;
  }
  return (
    <ol className={styles.steps}>
      {gaps.map((g) => (
        <li key={g.question}>
          <span className={styles.stepAt}>{g.best_distance.toFixed(3)}</span>
          <span className={styles.stepName}>{g.question}</span>
          <span className={styles.stepDetail}>
            limiar {overview.rag_max_distance}
            {g.occurrences > 1 && ` · ${g.occurrences}×`}
            {g.search_query && ` · buscou "${g.search_query}"`}
          </span>
        </li>
      ))}
    </ol>
  );
}
