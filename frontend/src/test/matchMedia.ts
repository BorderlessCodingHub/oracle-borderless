import { vi } from "vitest";

type Listener = (event: MediaQueryListEvent) => void;

export type MatchMediaStub = {
  /** Muda a preferência do "SO" e notifica quem estiver assinando. */
  setPrefersDark(value: boolean): void;
};

/**
 * jsdom não implementa matchMedia. Instala um stub controlável no global
 * e devolve o controle remoto dele. Lembre de `vi.unstubAllGlobals()` no afterEach.
 */
export function stubMatchMedia(prefersDark = false): MatchMediaStub {
  let dark = prefersDark;
  const listeners = new Set<Listener>();

  const stub = (query: string) => ({
    get matches() {
      return query.includes("prefers-color-scheme: dark") ? dark : false;
    },
    media: query,
    onchange: null,
    addEventListener: (_type: string, cb: Listener) => void listeners.add(cb),
    removeEventListener: (_type: string, cb: Listener) => void listeners.delete(cb),
    addListener: (cb: Listener) => void listeners.add(cb),
    removeListener: (cb: Listener) => void listeners.delete(cb),
    dispatchEvent: () => false,
  });

  vi.stubGlobal("matchMedia", stub);

  return {
    setPrefersDark(value: boolean) {
      dark = value;
      listeners.forEach((cb) => cb({ matches: value } as MediaQueryListEvent));
    },
  };
}
