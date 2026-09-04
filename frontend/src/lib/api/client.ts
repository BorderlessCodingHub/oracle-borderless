const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export function apiUrl(path: string): string {
  return `${BASE}${path}`;
}

/** 401 em qualquer chamada = sessão inválida/expirada/revogada (ADR-0018):
 * volta ao login preservando a rota. Não há storage a limpar — a credencial
 * é o cookie httpOnly, que o backend já invalidou. */
export function handleUnauthorized(): void {
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

/** fetch same-origin leva o cookie `ob_session` sozinho — nada de header. */
export async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(apiUrl(path));
  if (resp.status === 401) {
    handleUnauthorized();
    throw new Error("não autenticado");
  }
  if (!resp.ok) throw new Error(`GET ${path} failed: ${resp.status}`);
  return (await resp.json()) as T;
}
