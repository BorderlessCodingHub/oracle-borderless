import { afterEach, describe, expect, it } from "vitest";
import { clearSession, loadSession, peekSession, saveSession, type Session } from "./session";

const SAMPLE: Session = {
  user: { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" },
  accessToken: "jwt-abc",
  isAdmin: false,
};

afterEach(() => localStorage.clear());

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
});
