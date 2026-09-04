import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { clearSession, saveSession } from "../../lib/auth/session";
import { RequireAuth } from "./RequireAuth";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  clearSession(); // module-level memorySession (CRITICAL 2) não é resetado pelo storage.clear()
});

function renderAt(path = "/") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<div>tela de login</div>} />
          <Route
            path="*"
            element={
              <RequireAuth>
                <div>conteúdo privado</div>
              </RequireAuth>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

describe("RequireAuth", () => {
  it("deslogado: redireciona para /login", async () => {
    renderAt("/c/abc");
    expect(await screen.findByText("tela de login")).toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();
  });

  it("logado: renderiza o conteúdo", async () => {
    saveSession({
      user: { id: "u", email: "ana@x.com", name: null, username: null },
      accessToken: "jwt",
      isAdmin: false,
    });
    renderAt("/");
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });

  it("erro de sessão (storage bloqueado): não é 'deslogado' — mostra retry, não o login", async () => {
    const getItemSpy = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    renderAt("/c/abc");

    expect(await screen.findByText(/não foi possível verificar sua sessão/i)).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: /tentar de novo/i });
    expect(retryButton).toBeInTheDocument();
    // O ponto do terceiro estado: erro transitório NÃO deve derrubar para /login
    // nem, pelo lado oposto, liberar o conteúdo privado sem sessão de verdade.
    expect(screen.queryByText("tela de login")).not.toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();

    // Recupera: storage volta a funcionar e já tem sessão válida — retry deve
    // reavaliar e liberar o conteúdo (não apenas trocar de estado qualquer).
    getItemSpy.mockRestore();
    saveSession({
      user: { id: "u", email: "ana@x.com", name: null, username: null },
      accessToken: "jwt",
      isAdmin: false,
    });
    fireEvent.click(retryButton);
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });
});
