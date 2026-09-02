import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar conversations={[]} activeId={null} onNew={vi.fn()} onOpen={vi.fn()} />
    </MemoryRouter>
  );
}

describe("Sidebar", () => {
  it("rodapé traz as configurações de autenticação, não o tema", () => {
    renderSidebar();
    // O ThemeToggle mudou para o canto superior direito da tela (topbar do
    // ChatPage / Header do ops). Reintroduzi-lo aqui duplicaria o controle.
    expect(screen.queryByRole("group", { name: "Tema da interface" })).not.toBeInTheDocument();
    // O slot de auth mora no rodapé: identidade placeholder até /me existir.
    const foot = screen.getByTestId("sidebar-foot");
    expect(foot).toHaveTextContent("Visitante");
    expect(foot).toHaveTextContent(/autenticação/i);
  });

  it("não exibe identidade enquanto não há autenticação", () => {
    renderSidebar();
    expect(screen.queryByText(/@/)).not.toBeInTheDocument();
    expect(screen.queryByText(/autenticado na borda/i)).not.toBeInTheDocument();
  });

  it("lista vazia ganha um empty state em vez de espaço morto", () => {
    renderSidebar();
    expect(screen.getByText(/conversas aparecem aqui/i)).toBeInTheDocument();
  });
});
