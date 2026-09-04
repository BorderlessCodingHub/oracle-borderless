import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { SessionLoading } from "./SessionLoading";
import styles from "./RequireAuth.module.css";

/** Três estados, não dois (spec §5.2): erro transitório de sessão NÃO é
 * "deslogado" — sem isso, um soluço derruba usuário logado para o login. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, status, retry } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return <SessionLoading />;
  }
  if (status === "error") {
    return (
      <div className={styles.center}>
        <p>Não foi possível verificar sua sessão.</p>
        <button type="button" className={styles.retry} onClick={retry}>
          Tentar de novo
        </button>
      </div>
    );
  }
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}
