import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiUrl } from "../lib/api/client";
import {
  clearSession,
  loadSession,
  saveSession,
  type Session,
  type SessionUser,
} from "../lib/auth/session";

const DEMO = import.meta.env.VITE_DEMO_MODE === "true";

type AuthStatus = "loading" | "ready" | "error";

type AuthContextValue = {
  user: SessionUser | null;
  isAdmin: boolean;
  status: AuthStatus;
  /** null = sucesso; senão um código: invalid-credentials | rate-limited | unavailable */
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => void;
  retry: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const DEMO_SESSION: Session = {
  user: { id: "demo", email: "demo@borderless.dev", name: "Demo", username: "demo" },
  accessToken: "demo-token",
  isAdmin: true,
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const restore = useCallback(() => {
    if (DEMO) {
      setSession(DEMO_SESSION);
      setStatus("ready");
      return;
    }
    try {
      setSession(loadSession());
      setStatus("ready");
    } catch {
      // Storage bloqueado: terceiro estado — não tratar como deslogado (spec §5.2).
      setStatus("error");
    }
  }, []);

  useEffect(() => restore(), [restore]);

  const login = useCallback(async (email: string, password: string) => {
    let resp: Response;
    try {
      resp = await fetch(apiUrl("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
    } catch {
      return "unavailable";
    }
    if (!resp.ok) {
      const detail = await resp
        .json()
        .then((b) => b?.detail)
        .catch(() => null);
      if (detail === "invalid-credentials" || detail === "rate-limited") return detail;
      return "unavailable";
    }
    const body = await resp.json();
    const next: Session = {
      user: {
        id: body.user.id,
        email: body.user.email,
        name: body.user.name ?? null,
        username: body.user.username ?? null,
      },
      accessToken: body.access_token,
      isAdmin: body.is_admin === true,
    };
    saveSession(next);
    setSession(next);
    setStatus("ready");
    return null;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({
      user: session?.user ?? null,
      isAdmin: session?.isAdmin ?? false,
      status,
      login,
      logout,
      retry: restore,
    }),
    [session, status, login, logout, restore]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de <AuthProvider>");
  return context;
}
