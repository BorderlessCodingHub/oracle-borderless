import { Logo } from "../Logo/Logo";
import styles from "./RequireAuth.module.css";

/** Markup do estado "verificando sessão", compartilhado entre `RequireAuth`
 * (guard de rota privada) e `App` (guard do próprio roteador: sem isto, o
 * primeiro render acontece com `status === "loading"` e nenhuma sessão ainda
 * restaurada, então `isAdmin` é sempre `false` — a rota `/ops` nem monta e o
 * catch-all manda o admin para "/" antes do restore terminar). */
export function SessionLoading() {
  return (
    <div className={styles.center} aria-busy="true">
      <Logo size={56} />
      <p>Verificando sua sessão…</p>
    </div>
  );
}
