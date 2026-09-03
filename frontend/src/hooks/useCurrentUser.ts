import { useAuth } from "./useAuth";

/** Identidade real (ADR-0017), via sessão do AuthProvider.
 * isAdmin aqui é SÓ UI (monta ou não a rota /ops) — o backend decide com 404. */
export interface CurrentUser {
  email: string | null;
  isAdmin: boolean;
}

export function useCurrentUser(): CurrentUser {
  const { user, isAdmin } = useAuth();
  return { email: user?.email ?? null, isAdmin };
}
