import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../hooks/useAuth";
import { stubAuthFetch, TEST_USER } from "../../test/authFetch";
import LoginPage from "./LoginPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLogin(path = "/login") {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<div data-testid="app-root">app</div>} />
          <Route path="/c/abc" element={<div data-testid="conversa">conversa</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
}

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/e-mail/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/senha/i), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /entrar/i }));
}

const OK = () => new Response(JSON.stringify({ user: TEST_USER, is_admin: false }), { status: 200 });
const isLogin = (url: string) => url.endsWith("/auth/login");

describe("LoginPage", () => {
  it("sucesso navega para o next válido", async () => {
    stubAuthFetch(401, () => OK());
    renderLogin("/login?next=/c/abc");
    fill("ana@x.com", "s3nh4");
    expect(await screen.findByTestId("conversa")).toBeInTheDocument();
  });

  it("next externo é descartado (open redirect)", async () => {
    stubAuthFetch(401, () => OK());
    renderLogin("/login?next=//evil.com/x");
    fill("ana@x.com", "s3nh4");
    expect(await screen.findByTestId("app-root")).toBeInTheDocument();
  });

  it("credencial inválida mostra a mensagem traduzida", async () => {
    stubAuthFetch(401, () =>
      new Response(JSON.stringify({ detail: "invalid-credentials" }), { status: 401 })
    );
    renderLogin();
    fill("a@x.com", "errada");
    expect(await screen.findByText(/e-mail ou senha inválidos/i)).toBeInTheDocument();
  });

  it("forbidden mostra a mensagem da plataforma (única exceção ao erro traduzido)", async () => {
    stubAuthFetch(401, () =>
      new Response(
        JSON.stringify({ detail: "forbidden", message: "Sua conta está desativada." }),
        { status: 403 }
      )
    );
    renderLogin();
    fill("a@x.com", "s");
    expect(await screen.findByText("Sua conta está desativada.")).toBeInTheDocument();
  });

  it("não submete duas vezes enquanto espera", async () => {
    let resolve!: (r: Response) => void;
    const pending = new Promise<Response>((r) => (resolve = r));
    const fetchMock = stubAuthFetch(401, () => pending);
    renderLogin();
    fill("a@x.com", "s");
    fireEvent.click(screen.getByRole("button", { name: /entrando/i }));
    const loginCalls = fetchMock.mock.calls.filter(([input]) => isLogin(String(input)));
    expect(loginCalls).toHaveLength(1);
    resolve(OK());
    await waitFor(() => expect(screen.queryByTestId("app-root")).toBeInTheDocument());
  });
});
