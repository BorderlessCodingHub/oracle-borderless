import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../../hooks/useAuth";
import { loadSession, saveSession } from "../../../lib/auth/session";
import { Sidebar } from "./Sidebar";

afterEach(() => localStorage.clear());

function renderSidebar() {
  saveSession({
    user: { id: "u-1", email: "ana@x.com", name: "Ana", username: "ana" },
    accessToken: "jwt",
    isAdmin: false,
  });
  return render(
    <AuthProvider>
      <MemoryRouter>
        <Sidebar conversations={[]} activeId={null} onNew={vi.fn()} onOpen={vi.fn()} />
      </MemoryRouter>
    </AuthProvider>
  );
}

describe("Sidebar", () => {
  it("rodapé mostra a conta logada e o sair — sem controle de tema", async () => {
    renderSidebar();
    expect(screen.queryByRole("group", { name: "Tema da interface" })).not.toBeInTheDocument();
    const foot = screen.getByTestId("sidebar-foot");
    expect(foot).toHaveTextContent("ana@x.com");
    fireEvent.click(screen.getByRole("button", { name: /sair/i }));
    expect(loadSession()).toBeNull();
  });

  it("lista vazia ganha um empty state em vez de espaço morto", () => {
    renderSidebar();
    expect(screen.getByText(/conversas aparecem aqui/i)).toBeInTheDocument();
  });
});
