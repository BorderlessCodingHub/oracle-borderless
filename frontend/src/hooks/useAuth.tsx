import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiUrl } from "../lib/api/client";

const DEMO = import.meta.env.VITE_DEMO_MODE === "true";

/** Identidade do usuário logado (ADR-0018). O SPA NÃO guarda credencial: a
 * sessão é o cookie httpOnly `ob_session`, que o browser manda sozinho. Este
 * estado vive só em memória e é restaurado por GET /auth/me a cada boot.
 * isAdmin aqui é SÓ UI — o backend recalcula e responde 404. */
export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  username: string | null;
}

export type LoginErrorCode = "invalid-credentials" | "rate-limited" | "forbidden" | "unavailable";

/** `message` só vem em `forbidden`: é a mensagem da plataforma, voltada ao
 * usuário (única exceção à regra "nunca o erro cru" — spec §3). */
export interface LoginError {
  code: LoginErrorCode;
  message?: string;
}

type AuthStatus = "loading" | "ready" | "error";

type AuthSession = { user: AuthUser; isAdmin: boolean };

type AuthContextValue = {
  user: AuthUser | null;
  isAdmin: boolean;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<LoginError | null>;
  logout: () => Promise<void>;
  retry: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const DEMO_SESSION: AuthSession = {
  user: { id: "demo", email: "demo@borderless.dev", name: "Demo", username: "demo" },
  isAdmin: true,
};

/** Lança se o corpo não bate com o contrato de /auth/login e /auth/me. */
function parseSession(body: unknown): AuthSession {
  const b = body as { user?: Partial<AuthUser>; is_admin?: unknown } | null;
  if (!b || !b.user || typeof b.user.id !== "string" || typeof b.user.email !== "string") {
    throw new Error("sessão fora do contrato");
  }
  return {
    user: {
      id: b.user.id,
      email: b.user.email,
      name: b.user.name ?? null,
      username: b.user.username ?? null,
    },
    isAdmin: b.is_admin === true,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const restore = useCallback(async () => {
    if (DEMO) {
      setSession(DEMO_SESSION);
      setStatus("ready");
      return;
    }
    setStatus("loading");
    let resp: Response;
    try {
      resp = await fetch(apiUrl("/auth/me"));
    } catch {
      // Rede fora: NÃO é "deslogado" — terceiro estado com retry (spec §5).
      setStatus("error");
      return;
    }
    if (resp.status === 401) {
      setSession(null);
      setStatus("ready");
      return;
    }
    if (!resp.ok) {
      setStatus("error");
      return;
    }
    try {
      setSession(parseSession(await resp.json()));
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void restore();
  }, [restore]);

  const login = useCallback(async (email: string, password: string): Promise<LoginError | null> => {
    let resp: Response;
    try {
      resp = await fetch(apiUrl("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      return { code: "unavailable" };
    }
    if (!resp.ok) {
      const body = (await resp.json().catch(() => null)) as
        | { detail?: unknown; message?: unknown }
        | null;
      const detail = body?.detail;
      if (detail === "invalid-credentials" || detail === "rate-limited") return { code: detail };
      if (detail === "forbidden") {
        return {
          code: "forbidden",
          message: typeof body?.message === "string" ? body.message : undefined,
        };
      }
      return { code: "unavailable" };
    }
    // 200 não garante o contrato (proxy devolvendo HTML, corpo sem `user`):
    // sem este guard a exceção do parse deixava o form preso em "Entrando…".
    try {
      setSession(parseSession(await resp.json()));
      setStatus("ready");
      return null;
    } catch {
      return { code: "unavailable" };
    }
  }, []);

  const logout = useCallback(async () => {
    setSession(null);
    if (DEMO) return;
    try {
      await fetch(apiUrl("/auth/logout"), { method: "POST" });
    } catch {
      // Estado local já foi; o backend revoga na plataforma quando alcançável
      // e a sessão da plataforma expira sozinha em 7 dias.
    }
  }, []);

  const retry = useCallback(() => {
    void restore();
  }, [restore]);

  const value = useMemo(
    () => ({
      user: session?.user ?? null,
      isAdmin: session?.isAdmin ?? false,
      status,
      login,
      logout,
      retry,
    }),
    [session, status, login, logout, retry]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de <AuthProvider>");
  return context;
}
