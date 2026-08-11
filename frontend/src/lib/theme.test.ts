import { afterEach, describe, expect, it, vi } from "vitest";
import { stubMatchMedia } from "../test/matchMedia";
import {
  THEME_STORAGE_KEY,
  applyTheme,
  readStoredTheme,
  resolveTheme,
  storeTheme,
} from "./theme";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("readStoredTheme", () => {
  it("cai em 'system' quando não há nada salvo", () => {
    expect(readStoredTheme()).toBe("system");
  });

  it("cai em 'system' quando o valor salvo é inválido", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "roxo");
    expect(readStoredTheme()).toBe("system");
  });

  it("devolve o valor salvo quando é válido", () => {
    storeTheme("dark");
    expect(readStoredTheme()).toBe("dark");
  });
});

describe("resolveTheme", () => {
  it("segue o SO quando o modo é 'system'", () => {
    stubMatchMedia(true);
    expect(resolveTheme("system")).toBe("dark");
  });

  it("segue o SO no claro também", () => {
    stubMatchMedia(false);
    expect(resolveTheme("system")).toBe("light");
  });

  it("ignora o SO quando o modo é explícito", () => {
    stubMatchMedia(true);
    expect(resolveTheme("light")).toBe("light");
  });
});

describe("applyTheme", () => {
  it("escreve o tema resolvido no <html> e o devolve", () => {
    stubMatchMedia(true);
    expect(applyTheme("system")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    expect(applyTheme("light")).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
