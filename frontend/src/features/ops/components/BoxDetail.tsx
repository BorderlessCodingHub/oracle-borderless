import type { MapBox } from "../architectureMap";
import styles from "../OpsPage.module.css";

export function BoxDetail({ box }: { box: MapBox | null }) {
  if (!box) {
    return (
      <aside className={styles.detail}>
        <p className={styles.muted}>
          Clique numa caixa do mapa para ver o que ela faz e onde ela mora.
        </p>
      </aside>
    );
  }
  return (
    <aside className={styles.detail}>
      <h4>{box.label}</h4>
      <p>{box.description}</p>
      <p className={styles.muted}>Implementado em:</p>
      <ul className={styles.fileList}>
        {box.files.map((f) => (
          <li key={f}><code>{f}</code></li>
        ))}
      </ul>
    </aside>
  );
}
