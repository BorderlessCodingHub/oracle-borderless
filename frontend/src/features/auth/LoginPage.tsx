import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Logo } from "../../components/Logo/Logo";
import { useAuth } from "../../hooks/useAuth";
import styles from "./LoginPage.module.css";

const ERROR_MESSAGES: Record<string, string> = {
  "invalid-credentials": "E-mail ou senha inválidos.",
  "rate-limited": "Muitas tentativas. Aguarde alguns minutos e tente de novo.",
  unavailable: "Não foi possível falar com a plataforma. Tente novamente em instantes.",
};

/** Só paths relativos internos — open redirect (lição §8 do spec). */
function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return; // token de login não é brinquedo de duplo clique
    setBusy(true);
    setError(null);
    const code = await login(email, password);
    setBusy(false);
    if (code) {
      setError(ERROR_MESSAGES[code] ?? ERROR_MESSAGES.unavailable);
      return;
    }
    navigate(safeNext(params.get("next")), { replace: true });
  }

  return (
    <main className={styles.page}>
      <form className={styles.card} onSubmit={submit}>
        <Logo size={56} />
        <h1>Entrar no Oráculo</h1>
        <p className={styles.hint}>
          Use as suas credenciais da plataforma Borderless. O oráculo não guarda a sua senha.
        </p>
        <label className={styles.field}>
          E-mail
          <input
            type="email"
            name="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          Senha
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <button type="submit" className={styles.submit} disabled={busy}>
          {busy ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
