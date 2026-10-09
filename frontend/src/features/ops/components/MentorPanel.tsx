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

  // Defesa contra shape inesperado (endpoint fora do ar, stub de teste
  // desatualizado, resposta que não é `{gaps, engagement}`): sem isso,
  // `insights.gaps`/`insights.engagement` vêm `undefined` e o `for...of` de
  // `groupByLesson` ou o `.map` abaixo explodem em render, derrubando a
  // OpsPage inteira sem error boundary.
  const gaps = Array.isArray(insights.gaps) ? insights.gaps : [];
  const engagement = Array.isArray(insights.engagement) ? insights.engagement : [];
  const backlog = groupByLesson(gaps);

  return (
    <div className={styles.map}>
      <section className={styles.band}>
        <h3 className={styles.bandTitle}>Backlog de conteúdo</h3>
        {backlog.length === 0 ? (
          // M3: says "últimos 30 dias" (the API's default `days`), not "nesta
          // janela" — this panel doesn't wire into the page's WindowPicker yet
          // (parked; see the fix-wave notes), so "janela" would be misleading.
          <p className={styles.muted}>Nenhuma pergunta sem cobertura nos últimos 30 dias.</p>
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
        {engagement.length === 0 ? (
          <p className={styles.muted}>Nenhum turno do modo mentor nos últimos 30 dias.</p>
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
              {engagement.map((row) => (
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
