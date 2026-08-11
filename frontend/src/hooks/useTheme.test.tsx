import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubMatchMedia } from "../test/matchMedia";
import { ThemeProvider, useTheme } from "./useTheme";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

function Probe() {
  const { theme, resolved, setTheme } = useTheme();
  return (
    <>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolved}</span>
      <button onClick={() => setTheme("light")}>claro</button>
    </>
  );
}

function renderProbe() {
  return render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>
  );
}

describe("ThemeProvider", () => {
  it("começa em 'system' e resolve pelo SO", () => {
    stubMatchMedia(true);
    renderProbe();
    expect(screen.getByTestId("theme")).toHaveTextContent("system");
    expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("persiste a escolha explícita e aplica no <html>", () => {
    stubMatchMedia(true);
    renderProbe();
    fireEvent.click(screen.getByText("claro"));
    expect(screen.getByTestId("resolved")).toHaveTextContent("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("ob-theme")).toBe("light");
  });

  it("acompanha o SO ao vivo enquanto estiver em 'system'", () => {
    const media = stubMatchMedia(false);
    renderProbe();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    act(() => media.setPrefersDark(true));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("ignora o SO depois de uma escolha explícita", () => {
    const media = stubMatchMedia(false);
    renderProbe();
    fireEvent.click(screen.getByText("claro"));
    act(() => media.setPrefersDark(true));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("restaura a preferência salva ao montar", () => {
    stubMatchMedia(true);
    localStorage.setItem("ob-theme", "light");
    renderProbe();
    expect(screen.getByTestId("theme")).toHaveTextContent("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});
