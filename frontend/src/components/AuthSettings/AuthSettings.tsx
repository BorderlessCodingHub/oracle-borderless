import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import styles from "./AuthSettings.module.css";

/** Conta logada no rodapé da sidebar: identidade + sair (ADR-0017). */
export function AuthSettings() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null; // atrás do RequireAuth isso não acontece; guarda barata

  function signOut() {
    logout();
    navigate("/login");
  }

  const displayName = user.name || user.email;
  return (
    <div className={styles.account}>
      <span className={styles.avatar} aria-hidden="true">
        {displayName[0]?.toUpperCase() ?? "?"}
      </span>
      <span className={styles.identity}>
        <strong className={styles.name}>{displayName}</strong>
        <span className={styles.status}>{user.email}</span>
      </span>
      <button type="button" className={styles.signOut} onClick={signOut}>
        Sair
      </button>
    </div>
  );
}
