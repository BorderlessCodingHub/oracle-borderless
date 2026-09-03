import { clearSession, peekSession } from "../auth/session";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${BASE}${path}`;
}

export function authHeaders(): Record<string, string> {
  const session = peekSession();
  return session ? { Authorization: `Bearer ${session.accessToken}` } : {};
}

/** 401 em qualquer chamada = sessão inválida/expirada (sem refresh na v1):
 * limpa e volta ao login preservando a rota (spec §5.3). */
export function handleUnauthorized(): void {
  clearSession();
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(apiUrl(path), { headers: authHeaders() });
  if (resp.status === 401) {
    handleUnauthorized();
    throw new Error("não autenticado");
  }
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  return (await resp.json()) as T;
}
