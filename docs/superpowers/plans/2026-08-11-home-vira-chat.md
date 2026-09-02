# Home vira o chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar a raiz do site no chat do oráculo e remover a landing, a página Sobre & Fontes e a Base de conhecimento, que não têm mais função — o produto não é vendido e só o ecossistema tem acesso.

**Architecture:** `/` e `/c/:conversationId` passam a renderizar o `ChatPage`; `/oracle` e `/oracle/:id` viram redirects para não quebrar links já compartilhados. As três features removidas são deletadas por completo, com CSS modules e testes. O `Header` sobrevive porque a `OpsPage` o usa, mas perde toda a navegação. O empty state ganha exemplos alinhados ao escopo real da base.

**Tech Stack:** React 18, react-router-dom, Vite, TypeScript, Vitest + Testing Library.

## Global Constraints

- Fase 1b da spec `docs/superpowers/specs/2026-08-11-mvp-lancamento-fase1-design.md`.
- **Nenhum endpoint de backend é removido.** `ListKnowledgeSectionsAction` e `CountKnowledgeBaseAction` continuam em uso pela `AnswerQuestionAction` e pelo `GetOpsOverviewAction`; a `KnowledgePage` era conteúdo estático.
- **`/ops` continua existindo e continua sem link.** A guarda `isAdmin` em `App.tsx` permanece, pronta para a fase de autenticação.
- **`ThemeToggle` permanece na sidebar.** `ChatPage.module.css` depende do seletor `.sidebarFoot > [role="group"]` para o layout; remover o toggle de lá quebra o rodapé da sidebar.
- A máquina do sentinel `[demo-error]` em `frontend/src/lib/demo/demoStream.ts` **permanece** — só o card que a dispara sai da interface. `demoStream.test.ts` e `useAskStream.test.ts` continuam passando sem alteração.
- Sem cor crua no CSS: `noRawColors.test.ts` falha se um valor de cor literal entrar. Use tokens.
- Rodar testes: `cd frontend && npm test`. Checagem de tipos: `npx tsc --noEmit`.

---

### Task 1: `/` renderiza o chat, `/c/:id` as conversas

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/features/chat/ChatPage.tsx:107`, `:140`
- Test: `frontend/src/App.test.tsx` (criar)

**Interfaces:**
- Consumes: `ChatPage` (default export), `OpsPage` (default export), `useCurrentUser(): { email, isAdmin }`
- Produces: rotas `/` e `/c/:conversationId` servindo o `ChatPage`; `/oracle` e `/oracle/:conversationId` redirecionando

- [ ] **Step 1: Write the failing test**

Crie `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "./hooks/useTheme";
import { stubMatchMedia } from "./test/matchMedia";
import App from "./App";

// O ChatPage faz fetch de conversas no mount; um stub silencioso basta, o que
// está sob teste é o roteamento, não o carregamento de dados.
function renderAt(path: string) {
  stubMatchMedia(true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }))
  );
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("roteamento", () => {
  it("serve o chat na raiz", async () => {
    renderAt("/");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("serve o chat em /c/:id", async () => {
    renderAt("/c/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("redireciona /oracle para a raiz", async () => {
    renderAt("/oracle");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("redireciona /oracle/:id preservando a conversa", async () => {
    renderAt("/oracle/abc-123");
    expect(await screen.findByRole("textbox")).toBeInTheDocument();
  });

  it("não serve mais /about nem /knowledge", () => {
    renderAt("/about");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: FAIL — a raiz renderiza a `LandingPage`, que não tem `textbox`

- [ ] **Step 3: Write minimal implementation**

Substitua `frontend/src/App.tsx` por:

```tsx
import { Routes, Route, Navigate, useParams } from "react-router-dom";
import ChatPage from "./features/chat/ChatPage";
import OpsPage from "./features/ops/OpsPage";
import { useCurrentUser } from "./hooks/useCurrentUser";

/** Links de /oracle/:id já foram compartilhados; preservam a conversa. */
function LegacyConversationRedirect() {
  const { conversationId } = useParams();
  return <Navigate to={`/c/${conversationId}`} replace />;
}

export default function App() {
  const { isAdmin } = useCurrentUser();
  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      <Route path="/c/:conversationId" element={<ChatPage />} />
      <Route path="/oracle" element={<Navigate to="/" replace />} />
      <Route path="/oracle/:conversationId" element={<LegacyConversationRedirect />} />
      {/* Sem admin, a rota nem existe — ver useCurrentUser. */}
      {isAdmin && <Route path="/ops" element={<OpsPage />} />}
    </Routes>
  );
}
```

Em `frontend/src/features/chat/ChatPage.tsx`, linha 107, substitua:

```tsx
      navigate(`/oracle/${stream.conversationId}`, { replace: true });
```

por:

```tsx
      navigate(`/c/${stream.conversationId}`, { replace: true });
```

Na linha 140, substitua:

```tsx
    navigate("/oracle");
```

por:

```tsx
    navigate("/");
```

E na linha 158, no `onOpen` do `Sidebar`, substitua:

```tsx
          onOpen={(id) => navigate(`/oracle/${id}`)}
```

por:

```tsx
          onOpen={(id) => navigate(`/c/${id}`)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/features/chat/ChatPage.tsx
git commit -m "feat(frontend): raiz serve o chat e /oracle vira redirect"
```

---

### Task 2: Deletar landing, Sobre & Fontes e Base de conhecimento

**Files:**
- Delete: `frontend/src/features/landing/` (diretório inteiro)
- Delete: `frontend/src/features/about/` (diretório inteiro)
- Delete: `frontend/src/features/knowledge/` (diretório inteiro)
- Modify: `frontend/src/components/Header/Header.tsx`
- Modify: `frontend/src/components/Header/Header.test.tsx`
- Modify: `frontend/src/features/chat/components/Sidebar.tsx:51-53`

**Interfaces:**
- Consumes: rotas da Task 1
- Produces: `Header` renderizando apenas marca e `ThemeToggle`; `Sidebar` sem links para páginas removidas

- [ ] **Step 1: Write the failing test**

Substitua o teste em `frontend/src/components/Header/Header.test.tsx` pelo bloco `describe` abaixo, mantendo os imports e o `afterEach` que já existem:

```tsx
describe("Header", () => {
  it("monta dentro de ThemeProvider e expõe o ThemeToggle", () => {
    // Header -> ThemeToggle -> useTheme() explode sem ThemeProvider (regra 7 do
    // fix wave): este teste pina o ponto de montagem real e essa dependência.
    stubMatchMedia(true);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Header />
        </MemoryRouter>
      </ThemeProvider>
    );
    // [role="group"] é o mesmo seletor de que ChatPage.module.css depende
    // (`.sidebarFoot > [role="group"]`) para o layout da sidebar.
    expect(screen.getByRole("group", { name: "Tema da interface" })).toBeInTheDocument();
  });

  it("não navega para nenhuma página removida", () => {
    stubMatchMedia(true);
    render(
      <ThemeProvider>
        <MemoryRouter>
          <Header />
        </MemoryRouter>
      </ThemeProvider>
    );
    expect(screen.queryByRole("link", { name: /sobre/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /base de conhecimento/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /abrir o oráculo/i })).not.toBeInTheDocument();
    // A marca continua levando à raiz — agora, o próprio chat.
    expect(screen.getByRole("link", { name: /oracle borderless/i })).toHaveAttribute("href", "/");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Header/Header.test.tsx`
Expected: FAIL — os links "Sobre & Fontes", "Base de conhecimento" e o CTA ainda estão no DOM

- [ ] **Step 3: Write minimal implementation**

Substitua `frontend/src/components/Header/Header.tsx` por:

```tsx
import { Link } from "react-router-dom";
import { Logo } from "../Logo/Logo";
import { ThemeToggle } from "../ThemeToggle/ThemeToggle";
import styles from "./Header.module.css";

/**
 * Sobrou para a página de ops. O produto não tem mais navegação: a raiz é o
 * chat, e /ops é alcançável só por quem digita a URL.
 */
export function Header() {
  return (
    <header className={styles.header}>
      <div className={`container ${styles.inner}`}>
        <Link to="/" className={styles.brand}>
          <Logo size={40} />
          <span className={styles.brandText}>Oracle <span className="text-gradient">Borderless</span></span>
        </Link>
        <nav className={styles.nav}>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
```

Em `frontend/src/features/chat/components/Sidebar.tsx`, remova as duas linhas de link do `sidebarFoot`:

```tsx
        <Link to="/about">Sobre &amp; Fontes</Link>
        <Link to="/knowledge">Base de conhecimento</Link>
```

Se o import de `Link` ficar sem uso no arquivo, remova-o também.

Delete os três diretórios:

```bash
rm -rf frontend/src/features/landing frontend/src/features/about frontend/src/features/knowledge
```

- [ ] **Step 4: Run tests and type-check**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS em tudo. `tsc --noEmit` é o que garante que nenhum import das features deletadas sobrou.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src
git commit -m "feat(frontend): remove landing, Sobre & Fontes e Base de conhecimento"
```

---

### Task 3: Empty state alinhado ao escopo real

**Files:**
- Modify: `frontend/src/features/chat/components/EmptyState.tsx`
- Test: `frontend/src/features/chat/components/EmptyState.test.tsx` (criar)

**Interfaces:**
- Consumes: `onPick: (q: string) => void` — assinatura atual, inalterada
- Produces: `EmptyState` sem o card de demonstração de erro

- [ ] **Step 1: Write the failing test**

Crie `frontend/src/features/chat/components/EmptyState.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("não expõe o gatilho de erro de demonstração", () => {
    render(<EmptyState onPick={vi.fn()} />);
    expect(screen.queryByText(/estado de erro/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[demo-error\]/)).not.toBeInTheDocument();
  });

  it("manda a pergunta do card clicado", async () => {
    const onPick = vi.fn();
    render(<EmptyState onPick={onPick} />);

    const [first] = screen.getAllByRole("button");
    await userEvent.click(first);

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0]).toEqual(expect.any(String));
    expect(onPick.mock.calls[0][0]).not.toContain("demo");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/chat/components/EmptyState.test.tsx`
Expected: FAIL no primeiro teste — o card "Ver o estado de erro (falha ao gerar)" está no DOM

- [ ] **Step 3: Write minimal implementation**

Substitua o array `EXAMPLES` em `frontend/src/features/chat/components/EmptyState.tsx` por:

```tsx
// Perguntas dos roots que a base realmente cobre. Exemplo fora do escopo cai na
// recusa padrão e ensina a pessoa errado logo no primeiro contato.
const EXAMPLES = [
  { tag: "PRODUTOS", text: "Como funciona o Web3 Global Developer?" },
  { tag: "CULTURA", text: "O que diz o Código de Cultura sobre feedback?" },
  { tag: "PAPÉIS", text: "Quais são os papéis do Mapa Global?" },
  { tag: "DOMÍNIOS", text: "Quais domínios e subdomínios existem no ecossistema?" },
];
```

E simplifique o `onClick`, já que nenhum card carrega mais `value`:

```tsx
          <button key={e.tag} className={styles.exampleCard} onClick={() => onPick(e.text)}>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/chat/components/EmptyState.test.tsx src/lib/demo/demoStream.test.ts`
Expected: PASS. `demoStream.test.ts` continua passando — o sentinel segue existindo, só não é mais oferecido na interface.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/components/EmptyState.tsx frontend/src/features/chat/components/EmptyState.test.tsx
git commit -m "feat(frontend): exemplos do empty state dentro do escopo da base"
```

---

### Task 4: Remover a identidade placeholder

**Files:**
- Modify: `frontend/src/features/chat/ChatPage.tsx:15`, `:159`, `:167`
- Modify: `frontend/src/features/chat/components/Sidebar.tsx:12`, `:32`, `:55-58`
- Test: `frontend/src/features/chat/components/Sidebar.test.tsx` (criar)

**Interfaces:**
- Consumes: nada de tarefas anteriores
- Produces: `Sidebar` sem a prop `userEmail`; `ChatPage` sem a constante `USER_EMAIL` e sem o chip de e-mail na topbar

- [ ] **Step 1: Write the failing test**

Crie `frontend/src/features/chat/components/Sidebar.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/chat/components/Sidebar.test.tsx`
Expected: FAIL — TypeScript reclama da prop `userEmail` ausente, e "autenticado na borda" está no DOM

- [ ] **Step 3: Write minimal implementation**

Em `frontend/src/features/chat/components/Sidebar.tsx`:

Remova `userEmail: string;` da interface `Props` (linha 12) e o parâmetro da desestruturação (linha 32), que passa a ser:

```tsx
export function Sidebar({ conversations, activeId, onNew, onOpen }: Props) {
```

Remova o bloco do chip inteiro (linhas 55-58):

```tsx
        <div className={styles.userChip}>
          <span className={styles.avatar}>{userEmail[0]?.toUpperCase()}</span>
          <div><strong>{userEmail}</strong><span>autenticado na borda</span></div>
        </div>
```

Em `frontend/src/features/chat/ChatPage.tsx`, remova a linha 15:

```tsx
const USER_EMAIL = "duanne@mail.com"; // demo placeholder; real identity is a fast-follow
```

Remova a prop na chamada do `Sidebar` (linha 159):

```tsx
          userEmail={USER_EMAIL}
```

E remova o chip da topbar (linha 167):

```tsx
          <span className={styles.emailChip}>{USER_EMAIL}</span>
```

Deixe uma nota no lugar, para a fase de autenticação:

```tsx
          {/* Identidade volta aqui quando /me existir (fase de autenticação). */}
```

Em `frontend/src/features/chat/ChatPage.module.css`, remova as regras `.emailChip`, `.userChip` e `.avatar` se nenhum outro seletor as usar — confirme com `grep -rn "emailChip\|userChip\|avatar" frontend/src`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: PASS em tudo, incluindo `noRawColors.test.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/
git commit -m "fix(frontend): remove identidade placeholder até haver autenticação"
```

---

### Task 5: Verificação final

**Files:**
- Nenhum arquivo modificado; é a checagem de que a fatia está inteira.

**Interfaces:**
- Consumes: Tasks 1-4

- [ ] **Step 1: Suíte completa do frontend**

Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`
Expected: PASS em tudo, build gerado sem aviso de import não resolvido

- [ ] **Step 2: Nenhuma referência remanescente**

Run:

```bash
grep -rn "features/landing\|features/about\|features/knowledge\|/oracle\|USER_EMAIL" frontend/src --include=*.ts --include=*.tsx
```

Expected: saída vazia. Qualquer ocorrência é referência a página deletada ou a rota antiga que escapou.

- [ ] **Step 3: Conferir a aparência no navegador**

Run: `cd frontend && npm run dev`

Confira, com o backend rodando:
1. A raiz abre o chat com o empty state e o composer utilizável.
2. Clicar num card de exemplo dispara a pergunta.
3. Uma pergunta nova muda a URL para `/c/<id>` e a conversa aparece na sidebar.
4. Abrir `/oracle/<id>` de uma conversa existente redireciona para `/c/<id>` com o histórico carregado.
5. `/ops` continua abrindo, e o header dela mostra só marca e toggle de tema.
6. Nenhum e-mail aparece na topbar ou na sidebar.

- [ ] **Step 4: Commit**

Se algum ajuste tiver saído dos passos acima:

```bash
git add -A frontend/src
git commit -m "fix(frontend): ajustes da verificação final da home-chat"
```
