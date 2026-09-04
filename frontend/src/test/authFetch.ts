import { vi } from "vitest";

/** Sessão fake respondida por GET /auth/me (ADR-0018: o SPA não tem storage
 * de sessão — a única fonte de identidade é esse endpoint). */
export const TEST_USER = { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" };

export type MeOutcome =
  | { user: typeof TEST_USER; is_admin: boolean } // 200
  | 401 // deslogado
  | "network"; // falha de rede → status "error" no AuthProvider

export const loggedIn = (isAdmin = false): MeOutcome => ({ user: TEST_USER, is_admin: isAdmin });

type Fallback = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Stub global de `fetch` que resolve /auth/me e /auth/logout e delega o resto
 * a `fallback` (default: `[]` com 200). `setMe` troca o desfecho do /auth/me
 * no meio do teste (ex.: rede volta → retry). */
export function stubAuthFetch(me: MeOutcome, fallback?: Fallback) {
  const state = { me };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/auth/me")) {
      if (state.me === "network") throw new Error("down");
      if (state.me === 401) {
        return new Response(JSON.stringify({ detail: "not-authenticated" }), { status: 401 });
      }
      return new Response(JSON.stringify(state.me), { status: 200 });
    }
    if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
    if (fallback) return fallback(url, init);
    return new Response(JSON.stringify([]), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return Object.assign(fetchMock, {
    setMe(next: MeOutcome) {
      state.me = next;
    },
  });
}
