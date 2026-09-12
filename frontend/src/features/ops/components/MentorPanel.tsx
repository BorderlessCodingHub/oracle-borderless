import type { LessonGap, MentorInsights } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

/** Agrupa o backlog por aula — cada `lesson_id` vira uma pauta de gravação. */
function groupByLesson(gaps: LessonGap[]): [string, LessonGap[]][] {
  const grouped = new Map<string, LessonGap[]>();
  for (const gap of gaps) {
    const key = gap.lesson_id ?? "(sem aula)";
    grouped.set(key, [...(grouped.get(key) ?? []), gap]);
  }
  return [...grouped.entries()];
}

/** As duas leituras de produto do modo mentor (spec §9.3):
 *
 * - Backlog de conteúdo: perguntas que a aula não cobriu, agrupadas por aula
 *   — a pauta de quem vai regravar.
 * - Retenção por aula: turnos, alunos distintos e citações por turno — muitos
 *   turnos com poucas citações é aula confusa; muitos turnos com muitas
 *   citações é aula sendo minerada de verdade.
 */
export function MentorPanel({ insights }: { insights: MentorInsights | null }) {
  if (!insights) return null;

  const backlog = groupByLesson(insights.gaps);

  return (
    <div className={styles.map}>
      <section className={styles.band}>
        <h3 className={styles.bandTitle}>Backlog de conteúdo</h3>
        {backlog.length === 0 ? (
          <p className={styles.muted}>Nenhuma pergunta sem cobertura nesta janela.</p>
        ) : (
          backlog.map(([lessonId, gaps]) => (
            <div key={lessonId}>
              <p className={styles.boxLabel}>{lessonId}</p>
              <ol className={styles.steps}>
                {gaps.map((gap, i) => (
                  <li key={`${lessonId}-${i}`}>
                    <span className={styles.stepAt}>
                      {new Date(gap.asked_at).toLocaleDateString("pt-BR")}
                    </span>
                    <span className={styles.stepName}>{gap.question}</span>
                  </li>
                ))}
              </ol>
            </div>
          ))
        )}
      </section>

      <section className={styles.band}>
        <h3 className={styles.bandTitle}>Retenção por aula</h3>
        {insights.engagement.length === 0 ? (
          <p className={styles.muted}>Nenhum turno do modo mentor nesta janela.</p>
        ) : (
          <table className={styles.turns}>
            <thead>
              <tr>
                <th>Aula</th>
                <th>Turnos</th>
                <th>Alunos distintos</th>
                <th>Citações/turno</th>
                <th>% gap</th>
              </tr>
            </thead>
            <tbody>
              {insights.engagement.map((row) => (
                <tr key={row.lesson_id ?? "(sem aula)"}>
                  <td>{row.lesson_id ?? "(sem aula)"}</td>
                  <td>{row.turns}</td>
                  <td>{row.distinct_users}</td>
                  <td>{row.avg_citations.toFixed(1)}</td>
                  <td>{Math.round(row.gap_ratio * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
