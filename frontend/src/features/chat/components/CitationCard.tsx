import { useState } from "react";
import type { Citation } from "../../../lib/types";
import { safeUrl } from "../../../lib/utils/safeUrl";
import { toPlainText } from "../../../lib/utils/text";
import styles from "../ChatPage.module.css";

export function CitationCard({ citation, index }: { citation: Citation; index: number }) {
  const [open, setOpen] = useState(false);
  const isWeb = citation.source_type === "web";
  const href = isWeb ? safeUrl(citation.url) : null;
  const label = isWeb ? "Link externo" : "Base de conhecimento";
  const snippet = toPlainText(citation.snippet);
  return (
    <li className={styles.citation}>
      <button
        type="button"
        className={styles.citationHead}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={styles.citationIndex} aria-hidden="true">{index}</span>
        <span className={styles.citationTitle}>{citation.title}</span>
        <span className={styles.citationTag}>{label}</span>
        <span className={styles.citationChevron} aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className={styles.citationBody}>
          {snippet && <p>{snippet}</p>}
          {href && (
            <a href={href} target="_blank" rel="noreferrer">Abrir fonte →</a>
          )}
          {/* A tag no cabeçalho já diz "Base de conhecimento"; este fallback só
              evita uma expansão vazia quando não há trecho nem link. */}
          {!href && !snippet && (
            <span className={styles.citationRef}>Referência da base de conhecimento</span>
          )}
        </div>
      )}
    </li>
  );
}
