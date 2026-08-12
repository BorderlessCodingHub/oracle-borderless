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
    // O toggle continua no rodapé: ChatPage.module.css depende de
    // `.sidebarFoot > [role="group"]` para o layout.
    expect(screen.getByRole("group", { name: "Tema da interface" })).toBeInTheDocument();
  });
});
