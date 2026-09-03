import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { AuthProvider } from "./hooks/useAuth";
import { saveSession } from "./lib/auth/session";
import { stubMatchMedia } from "./test/matchMedia";
import App from "./App";

// Sonda montada junto do App para observar a rota final depois de qualquer
// redirect — é o único jeito confiável de provar que um <Navigate> aconteceu,
// já que o ChatPage renderiza o mesmo Composer em qualquer rota.
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

// O ChatPage faz fetch de conversas (lista) e, quando há :conversationId, de
// uma conversa específica (detalhe) no mount. O stub distingue as duas rotas
// porque o shape das respostas é diferente (array vs. objeto com messages) —
// um stub "achatado" que devolve [] para tudo faz a rota de detalhe explodir
// contra o parsing real (dto.messages.map), mascarando bugs de verdade. O que
// está sob teste aqui é o roteamento, não os dados, então o stub só precisa
// ser plausível o bastante para o ChatPage montar sem estourar.
function renderAt(path: string) {
  stubMatchMedia(true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (/\/conversations\/[^/]+$/.test(url)) {
        return new Response(
          JSON.stringify({ id: "abc-123", title: null, messages: [] }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify([]), { status: 200 });
    })
  );
  return render(
    <AuthProvider>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <LocationProbe />
          <App />
        </MemoryRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}

// Sessão semeada para os testes de roteamento que esperam o chat — sem ela o
// RequireAuth (Task 9) redireciona qualquer rota privada para /login.
function seedSession() {
  saveSession({
    user: { id: "u", email: "ana@x.com", name: null, username: null },
    accessToken: "jwt",
    isAdmin: false,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("roteamento", () => {
  it("serve o chat na raiz", async () => {
    seedSession();
    renderAt("/");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    // toHaveTextContent(string) faz substring — todo pathname contém "/", o
    // que tornaria esta asserção vacuamente verdadeira. Ancorado com regex.
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("serve o chat em /c/:id", async () => {
    seedSession();
    renderAt("/c/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/c\/abc-123$/);
  });

  it("redireciona /oracle para a raiz", async () => {
    seedSession();
    renderAt("/oracle");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("redireciona /oracle/:id preservando a conversa", async () => {
    seedSession();
    renderAt("/oracle/abc-123");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/c\/abc-123$/);
  });

  it("redireciona /about e /knowledge para a raiz (catch-all)", async () => {
    seedSession();
    const about = renderAt("/about");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
    about.unmount();

    renderAt("/knowledge");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("sem sessão, a raiz cai no /login", async () => {
    renderAt("/"); // sem saveSession
    expect(await screen.findByText(/entrar no oráculo/i)).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/login$/);
  });
});
