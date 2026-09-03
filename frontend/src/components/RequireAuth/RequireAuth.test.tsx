import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { saveSession } from "../../lib/auth/session";
import { RequireAuth } from "./RequireAuth";

afterEach(() => localStorage.clear());

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
});
