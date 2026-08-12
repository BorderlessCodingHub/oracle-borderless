import { Link } from "react-router-dom";
import { Logo } from "../../../components/Logo/Logo";
import { ThemeToggle } from "../../../components/ThemeToggle/ThemeToggle";
import type { ConversationSummary } from "../../../lib/types";
import styles from "../ChatPage.module.css";

type Props = {
  conversations: ConversationSummary[];
  activeId: string | null;
  onNew: () => void;
  onOpen: (id: string) => void;
};

const MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Small, dependency-free pt-BR relative date: "Hoje" / "Ontem" / "dd mmm". */
function formatConversationDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const diffDays = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);
  if (diffDays === 0) return "Hoje";
  if (diffDays === 1) return "Ontem";
  const dd = String(date.getDate()).padStart(2, "0");
  return `${dd} ${MONTHS_PT[date.getMonth()]}`;
}

export function Sidebar({ conversations, activeId, onNew, onOpen }: Props) {
  return (
    <aside className={styles.sidebar}>
      <Link to="/" className={styles.sidebarBrand}><Logo size={34} /> Oracle Borderless</Link>
      <button className={styles.newBtn} onClick={onNew}>+ Nova conversa</button>
      <div className={styles.listLabel}>Conversas</div>
      <ul className={styles.convList}>
        {conversations.map((c) => (
          <li key={c.id}>
            <button
              className={c.id === activeId ? styles.convActive : styles.convItem}
              onClick={() => onOpen(c.id)}
            >
              <strong>{c.title ?? "(sem título)"}</strong>
              <span className={styles.convMeta}>{formatConversationDate(c.updatedAt)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className={styles.sidebarFoot} data-testid="sidebar-foot">
        <ThemeToggle />
        {/* Identidade volta aqui quando /me existir (fase de autenticação). */}
      </div>
    </aside>
  );
}
