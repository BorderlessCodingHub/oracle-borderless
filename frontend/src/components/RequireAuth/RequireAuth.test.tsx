import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { loggedIn, stubAuthFetch } from "../../test/authFetch";
import { RequireAuth } from "./RequireAuth";

afterEach(() => {
  vi.unstubAllGlobals();
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
  it("deslogado (/auth/me 401): redireciona para /login", async () => {
    stubAuthFetch(401);
    renderAt("/c/abc");
    expect(await screen.findByText("tela de login")).toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();
  });

  it("logado (/auth/me 200): renderiza o conteúdo", async () => {
    stubAuthFetch(loggedIn());
    renderAt("/");
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });

  it("rede fora no /auth/me: não é 'deslogado' — mostra retry, não o login", async () => {
    const fetchMock = stubAuthFetch("network");
    renderAt("/c/abc");

    expect(await screen.findByText(/não foi possível verificar sua sessão/i)).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: /tentar de novo/i });
    // Erro transitório NÃO derruba para /login nem libera o conteúdo sem sessão.
    expect(screen.queryByText("tela de login")).not.toBeInTheDocument();
    expect(screen.queryByText("conteúdo privado")).not.toBeInTheDocument();

    // A rede volta e a sessão (cookie) ainda vale: retry reavalia e libera.
    fetchMock.setMe(loggedIn());
    fireEvent.click(retryButton);
    expect(await screen.findByText("conteúdo privado")).toBeInTheDocument();
  });
});
