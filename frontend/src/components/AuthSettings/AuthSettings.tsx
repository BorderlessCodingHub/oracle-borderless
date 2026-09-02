import { useCurrentUser } from "../../hooks/useCurrentUser";
import styles from "./AuthSettings.module.css";

/**
 * Configurações de autenticação — slot no rodapé da sidebar (onde ficava o
 * ThemeToggle, que subiu para o canto superior direito da tela).
 *
 * HOJE: identidade placeholder de useCurrentUser — não existe /me e o
 * mecanismo de auth é ponto em aberto (ver CLAUDE.md). QUANDO A AUTH CHEGAR:
 * o fluxo real de conta (entrar/sair, sessão) pluga aqui, sem mexer na Sidebar.
 */
export function AuthSettings() {
  const { email } = useCurrentUser();
  return (
    <div className={styles.account}>
      <span className={styles.avatar} aria-hidden="true">
        {email ? (
          email[0].toUpperCase()
        ) : (
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c1.8-3.2 4.6-5 8-5s6.2 1.8 8 5" />
          </svg>
        )}
      </span>
      <span className={styles.identity}>
        <strong className={styles.name}>{email ?? "Visitante"}</strong>
        <span className={styles.status}>{email ? "Conectado" : "Autenticação em breve"}</span>
      </span>
    </div>
  );
}
