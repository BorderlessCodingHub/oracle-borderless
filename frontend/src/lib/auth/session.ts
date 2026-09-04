/** Sessão do oráculo (ADR-0017): accessToken da plataforma + usuário.
 * localStorage + Bearer (não cookie): SPA e API podem estar em hosts distintos,
 * o SSE já é fetch, e evita CSRF. isAdmin aqui é SÓ UI — o backend recalcula. */

export interface SessionUser {
  id: string;
  email: string;
  name: string | null;
  username: string | null;
}

export interface Session {
  user: SessionUser;
  accessToken: string;
  isAdmin: boolean;
}

const KEY = "ob-session";

// Fallback em memória para quando o storage está bloqueado (modo privado +
// extensões). Sem isto: saveSession engolia o erro ("vale só em memória até o
// reload", dizia o comentário antigo) mas peekSession só lia do localStorage —
// então login funcionava, a chamada seguinte ia sem Authorization, 401,
// handleUnauthorized limpava e recarregava, e a sessão em memória (que nunca
// existiu) sumia: loop infinito de login. Vive só neste módulo, por aba.
let memorySession: Session | null = null;

/** Pode lançar se o storage estiver bloqueado E não houver sessão em memória —
 * o AuthProvider traduz isso no estado "error" com retry (spec §5.2). */
export function loadSession(): Session | null {
  if (memorySession) return memorySession;
  const raw = localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Session;
    return parsed && typeof parsed.accessToken === "string" && parsed.user ? parsed : null;
  } catch {
    return null; // corrompido = deslogado, não crash
  }
}

/** Nunca lança — para quem só precisa do token (client HTTP). */
export function peekSession(): Session | null {
  if (memorySession) return memorySession;
  try {
    return loadSession();
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  memorySession = session;
  try {
    localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Storage bloqueado: a sessão vale só em memória até o reload.
  }
}

export function clearSession(): void {
  memorySession = null;
  try {
    localStorage.removeItem(KEY);
  } catch {
    // idem
  }
}
