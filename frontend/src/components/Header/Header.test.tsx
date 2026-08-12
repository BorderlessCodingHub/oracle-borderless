import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../../hooks/useTheme";
import { stubMatchMedia } from "../../test/matchMedia";
import { Header } from "./Header";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("Header", () => {
  it("monta dentro de ThemeProvider e expõe o ThemeToggle", () => {
    // Header -> ThemeToggle -> useTheme() explode sem ThemeProvider (regra 7 do
    // fix wave): este teste pina o ponto de montagem real e essa dependência.
    stubMatchMedia(true);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Header />
        </MemoryRouter>
      </ThemeProvider>
    );
    expect(screen.getByRole("group", { name: "Tema da interface" })).toBeInTheDocument();
  });

  it("não navega para nenhuma página removida", () => {
    stubMatchMedia(true);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Header />
        </MemoryRouter>
      </ThemeProvider>
    );
    expect(screen.queryByRole("link", { name: /sobre/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /base de conhecimento/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /abrir o oráculo/i })).not.toBeInTheDocument();
    // /ops é restrição inegociável do plano: alcançável só por quem digita a
    // URL, nunca por link. Maior chance de alguém reintroduzir de boa-fé.
    expect(screen.queryByRole("link", { name: /^ops$/i })).not.toBeInTheDocument();
    // A marca continua levando à raiz — agora, o próprio chat.
    expect(screen.getByRole("link", { name: /oracle borderless/i })).toHaveAttribute("href", "/");
  });
});
