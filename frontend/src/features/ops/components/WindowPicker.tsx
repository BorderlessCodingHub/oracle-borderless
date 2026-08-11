import type { OpsWindow } from "../../../lib/types.ops";
import styles from "../OpsPage.module.css";

const LABELS: Record<OpsWindow, string> = {
  "24h": "24 horas",
  "7d": "7 dias",
  all: "Tudo",
};

export function WindowPicker({
  value,
  onChange,
}: {
  value: OpsWindow;
  onChange: (w: OpsWindow) => void;
}) {
  return (
    <div className={styles.windowPicker} role="group" aria-label="Janela de tempo">
      {(Object.keys(LABELS) as OpsWindow[]).map((w) => (
        <button
          key={w}
          type="button"
          aria-pressed={w === value}
          className={w === value ? styles.windowActive : styles.windowButton}
          onClick={() => onChange(w)}
        >
          {LABELS[w]}
        </button>
      ))}
    </div>
  );
}
