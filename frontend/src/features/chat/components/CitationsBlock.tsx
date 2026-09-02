import { useId, useState } from "react";
import type { Citation } from "../../../lib/types";
import { CitationCard } from "./CitationCard";
import styles from "../ChatPage.module.css";

/**
 * Fontes como nota de rodapé: recolhidas num resumo discreto ("N fontes") e
 * expandidas só quando a pessoa clica — a resposta é o protagonista, a
 * proveniência fica a um clique.
 */
export function CitationsBlock({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  if (!citations.length) return null;
  const label = citations.length === 1 ? "1 fonte" : `${citations.length} fontes`;
  return (
    <div className={styles.citations}>
      <button
        type="button"
        className={styles.citationsToggle}
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span aria-hidden="true" className={expanded ? styles.citationsChevronOpen : styles.citationsChevron}>▸</span>
        {label}
      </button>
      {expanded && (
        <ul id={listId} className={styles.citationList}>
          {citations.map((c, i) => (
            <CitationCard key={`${c.title}-${i}`} citation={c} index={i + 1} />
          ))}
        </ul>
      )}
    </div>
  );
}
