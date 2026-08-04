import type { EvalReportPayload } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

/**
 * O shape lido aqui é o que `evals/report.py::_report_dict` grava:
 * `passed` (não "verdict"), `metrics` como LISTA de agregados, `hard_failures`
 * com (case_id, category, metric, score).
 */
export function EvalPanel({ payload }: { payload: EvalReportPayload | null }) {
  if (!payload || payload.status === "no_runs" || !payload.report) {
    return (
      <div className={styles.empty}>
        <p>Nenhum run de eval ainda.</p>
        <p className={styles.muted}>
          Rode <code>python -m evals</code> para preencher este painel. O eval faz chamadas
          de modelo de verdade, então não é disparado pela web.
        </p>
      </div>
    );
  }
  const report = payload.report;
  const metrics = report.metrics ?? [];
  const hardFailures = report.hard_failures ?? [];
  return (
    <div className={styles.eval}>
      <p className={report.passed ? styles.pass : styles.fail}>
        Veredito: {report.passed ? "PASSOU" : "FALHOU"}
      </p>
      <p className={styles.muted}>
        Último run: {new Date(report.ran_at).toLocaleString("pt-BR")}
      </p>
      <table className={styles.turns}>
        <thead><tr><th>Métrica</th><th>Média</th><th>Mínimo</th><th>Casos</th><th></th></tr></thead>
        <tbody>
          {metrics.map((m) => (
            <tr key={m.metric}>
              <td>{m.metric}</td>
              <td>{m.mean.toFixed(2)}</td>
              <td>{m.threshold.toFixed(2)}</td>
              <td>{m.n}</td>
              <td className={m.passed ? styles.pass : styles.fail}>
                {m.passed ? "ok" : "abaixo"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hardFailures.length > 0 && (
        <p className={styles.fail}>
          {hardFailures.length} caso(s) de segurança abaixo do piso — ver o report completo.
        </p>
      )}
      {payload.history.length > 1 && (
        <p className={styles.muted}>{payload.history.length} runs no histórico.</p>
      )}
    </div>
  );
}
