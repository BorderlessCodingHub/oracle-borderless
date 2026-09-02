import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../../../hooks/useTheme";
import { stubMatchMedia } from "../../../test/matchMedia";
import { Sidebar } from "./Sidebar";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("Sidebar", () => {
  it("não exibe identidade enquanto não há autenticação", () => {
    stubMatchMedia(true);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Sidebar conversations={[]} activeId={null} onNew={vi.fn()} onOpen={vi.fn()} />
        </MemoryRouter>
      </ThemeProvider>
    );

    expect(screen.queryByText(/@/)).not.toBeInTheDocument();
    expect(screen.queryByText(/autenticado na borda/i)).not.toBeInTheDocument();
    // ChatPage.module.css depende de `.sidebarFoot > [role="group"]` (filho
    // DIRETO) para o layout do rodapé. Checar só a presença do role="group"
    // em algum lugar da árvore não provaria isso — mover o ThemeToggle para
    // fora do .sidebarFoot manteria essa asserção verde. CSS Modules hasheia
    // a classe, então usamos data-testid no container em vez de className
    // para identificar o pai de forma estável.
    const foot = screen.getByTestId("sidebar-foot");
    const group = screen.getByRole("group", { name: "Tema da interface" });
    expect(group.parentElement).toBe(foot);
  });
});
