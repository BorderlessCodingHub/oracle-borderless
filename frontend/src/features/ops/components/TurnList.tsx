import type { TurnSummary } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

const OUTCOME_LABEL: Record<string, string> = {
  answer: "resposta",
  refusal: "recusa",
  error: "erro",
};

function gateLabel(t: TurnSummary): string {
  if (t.gate_degraded) return "degraded";
  return t.gate_retrieve ? "retrieve" : "skip";
}

export function TurnList({
  turns,
  selectedId,
  onSelect,
}: {
  turns: TurnSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (turns.length === 0) {
    return (
      <p className={styles.muted}>
        Nenhum turno nesta janela. Faça uma pergunta no oráculo e volte aqui.
      </p>
    );
  }
  return (
    <table className={styles.turns}>
      <thead>
        <tr>
          <th>Hora</th><th>Pergunta</th><th>Gate</th><th>Chunks</th><th>Desfecho</th><th>Duração</th>
        </tr>
      </thead>
      <tbody>
        {turns.map((t) => (
          <tr
            key={t.id}
            onClick={() => onSelect(t.id)}
            className={t.id === selectedId ? styles.turnActive : undefined}
          >
            <td>{new Date(t.created_at).toLocaleTimeString("pt-BR")}</td>
            <td className={styles.question}>{t.question}</td>
            <td>{gateLabel(t)}</td>
            <td>{t.retrieval_kept}</td>
            <td>{OUTCOME_LABEL[t.outcome] ?? t.outcome}</td>
            <td>{t.engine_ms === null ? "—" : `${t.engine_ms}ms`}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
