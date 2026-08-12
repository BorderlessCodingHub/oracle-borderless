import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { stubMatchMedia } from "./test/matchMedia";
import App from "./App";

// O ChatPage faz fetch de conversas no mount; um stub silencioso basta, o que
// está sob teste é o roteamento, não o carregamento de dados.
function renderAt(path: string) {
  stubMatchMedia(true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }))
  );
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("roteamento", () => {
  it("serve o chat na raiz", async () => {
    renderAt("/");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("serve o chat em /c/:id", async () => {
    renderAt("/c/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("redireciona /oracle para a raiz", async () => {
    renderAt("/oracle");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("redireciona /oracle/:id preservando a conversa", async () => {
    renderAt("/oracle/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("não serve mais /about nem /knowledge", () => {
    renderAt("/about");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
