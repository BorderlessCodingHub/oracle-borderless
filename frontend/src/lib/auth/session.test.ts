import { afterEach, describe, expect, it, vi } from "vitest";
import { clearSession, loadSession, peekSession, saveSession, type Session } from "./session";

const SAMPLE: Session = {
  user: { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" },
  accessToken: "jwt-abc",
  isAdmin: false,
};

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  clearSession(); // module-level memorySession não é resetado pelo storage.clear()
});

describe("session", () => {
  it("salva, carrega e limpa", () => {
    saveSession(SAMPLE);
    expect(loadSession()).toEqual(SAMPLE);
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it("conteúdo corrompido no storage vira null, não exceção", () => {
    localStorage.setItem("ob-session", "{nao-e-json");
    expect(loadSession()).toBeNull();
    expect(peekSession()).toBeNull();
  });

  // CRITICAL 2: com storage bloqueado, saveSession não pode deixar a sessão
  // sem efeito nenhum — senão login funciona mas a chamada seguinte sai sem
  // Authorization, 401 dispara handleUnauthorized, que limpa e recarrega, e
  // como a "sessão em memória" nunca existiu, o login some: loop infinito.
  it("storage bloqueado: saveSession ainda deixa a sessão disponível via memória", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    saveSession(SAMPLE);

    expect(peekSession()).toEqual(SAMPLE);
    expect(loadSession()).toEqual(SAMPLE);
  });
});
