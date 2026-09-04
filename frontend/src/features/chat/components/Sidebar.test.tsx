import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../../hooks/useAuth";
import { loggedIn, stubAuthFetch } from "../../../test/authFetch";
import { Sidebar } from "./Sidebar";

afterEach(() => vi.unstubAllGlobals());

function renderSidebar() {
  const fetchMock = stubAuthFetch(loggedIn());
  render(
    <AuthProvider>
      <MemoryRouter>
        <Sidebar conversations={[]} activeId={null} onNew={vi.fn()} onOpen={vi.fn()} />
      </MemoryRouter>
    </AuthProvider>
  );
  return fetchMock;
}

describe("Sidebar", () => {
  it("rodapé mostra a conta logada e o sair — sem controle de tema", async () => {
    const fetchMock = renderSidebar();
    expect(screen.queryByRole("group", { name: "Tema da interface" })).not.toBeInTheDocument();
    // O rodapé só aparece depois que /auth/me responde (restore é assíncrono).
    expect(await screen.findByText("ana@x.com")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-foot")).toHaveTextContent("ana@x.com");

    fireEvent.click(screen.getByRole("button", { name: /sair/i }));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/logout$/),
      expect.objectContaining({ method: "POST" })
    );
  });

  it("lista vazia ganha um empty state em vez de espaço morto", () => {
    renderSidebar();
    expect(screen.getByText(/conversas aparecem aqui/i)).toBeInTheDocument();
  });
});
