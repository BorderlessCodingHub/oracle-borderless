import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { AuthProvider } from "./hooks/useAuth";
import { loggedIn, stubAuthFetch, type MeOutcome } from "./test/authFetch";
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
// Shapes mínimos porém plausíveis dos endpoints de /ops (lib/types.ops.ts) —
// o suficiente para o OpsPage montar sem estourar contra acesso a campo
// ausente, sem precisar espelhar o conteúdo de verdade (o que está sob teste
// aqui é o roteamento admin, não os dados de ops).
const OPS_OVERVIEW_STUB = {
  window: "24h",
  knowledge: { documents_active: 0, documents_archived: 0, chunks: 0, sections: [] },
  sync: { job_name: null, status: null, started_at: null, finished_at: null, error: null },
  traces: {
    turns: 0,
    gate_retrieve: 0,
    gate_skip: 0,
    gate_degraded: 0,
    answers: 0,
    refusals: 0,
    errors: 0,
    avg_first_token_ms: null,
    max_first_token_ms: null,
    avg_engine_ms: null,
    max_engine_ms: null,
    avg_retrieval_kept: null,
    avg_best_distance: null,
  },
  rag_top_k: 6,
  rag_max_distance: 0.55,
  knowledge_gaps: [],
};
const OPS_EVAL_STUB = { status: "no_runs", report: null, history: [] };

function renderAt(path: string, me: MeOutcome = loggedIn()) {
  stubMatchMedia(true);
  stubAuthFetch(me, (url) => {
    if (/\/ops\/overview/.test(url)) {
      return new Response(JSON.stringify(OPS_OVERVIEW_STUB), { status: 200 });
    }
    if (/\/ops\/turns/.test(url)) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    if (/\/ops\/eval/.test(url)) {
      return new Response(JSON.stringify(OPS_EVAL_STUB), { status: 200 });
    }
    if (/\/conversations\/[^/]+$/.test(url)) {
      return new Response(JSON.stringify({ id: "abc-123", title: null, messages: [] }), {
        status: 200,
      });
    }
    return new Response(JSON.stringify([]), { status: 200 });
  });
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

// Sessão vem de GET /auth/me (ADR-0018) — o stub de fetch decide se o usuário está logado.

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
});

describe("roteamento", () => {
  it("serve o chat na raiz", async () => {
    renderAt("/");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    // toHaveTextContent(string) faz substring — todo pathname contém "/", o
    // que tornaria esta asserção vacuamente verdadeira. Ancorado com regex.
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("serve o chat em /c/:id", async () => {
    renderAt("/c/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/c\/abc-123$/);
  });

  it("redireciona /oracle para a raiz", async () => {
    renderAt("/oracle");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("redireciona /oracle/:id preservando a conversa", async () => {
    renderAt("/oracle/abc-123");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/c\/abc-123$/);
  });

  it("redireciona /about e /knowledge para a raiz (catch-all)", async () => {
    const about = renderAt("/about");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
    about.unmount();

    renderAt("/knowledge");
    await screen.findByRole("textbox");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/);
  });

  it("sem sessão, a raiz cai no /login", async () => {
    renderAt("/", 401); // /auth/me diz deslogado
    expect(await screen.findByText(/entrar no oráculo/i)).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/login$/);
  });

  // Regressão (CRITICAL 1): no primeiro render o AuthProvider está em
  // "loading" e sem sessão ainda restaurada — se o App montasse <Routes> já
  // nesse instante, isAdmin seria sempre false, a rota /ops nem existiria e o
  // catch-all mandaria o admin de volta para "/" antes do restore terminar.
  it("admin acessando /ops direto (deep-link) permanece em /ops após restaurar a sessão", async () => {
    renderAt("/ops", loggedIn(true));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(/^\/ops$/)
    );
  });
});
