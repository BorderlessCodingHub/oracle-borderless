# Autenticação — spec do Oracle Borderless

**Status:** aprovado em 03/09/2026 (brainstorm com a dona do produto). Substitui o
"ponto em aberto" de autenticação do `CLAUDE.md`. A decisão arquitetural vira o
**ADR-0017** (plataforma como IdP, JWT validado localmente, sem Supabase) antes
da implementação.

> Este documento nasceu do guia de replicação da auth do socratic-dev. O modelo
> de lá foi **adaptado, não copiado**: o contrato novo da plataforma devolve um
> `accessToken` no login, o que elimina a peça Supabase inteira (createUser sem
> senha, magic link e `verifyOtp` só existiam porque o contrato antigo não
> devolvia token). As lições de produção do guia que continuam válidas estão em §8.

---

## 1. O modelo em uma frase

**As credenciais (e-mail + senha) vivem na plataforma Borderless
(`api.borderlesscoding.com`). O oráculo nunca armazena senha.** O FastAPI faz o
*bridge*: envia as credenciais ao endpoint de signin da plataforma usando uma
**key header de app** (segredo que nunca sai do servidor) e repassa ao SPA o
`accessToken` (JWT) que a plataforma emitiu. A partir daí, toda requisição ao
backend leva `Authorization: Bearer <accessToken>` e o FastAPI **valida o JWT
localmente**, sem ida à rede.

Consequências:

- A plataforma é a única fonte de verdade das credenciais e do token.
- **Sem autenticação, não há pergunta**: `/conversations/*` exige usuário válido
  (401 sem token); o frontend bloqueia o chat atrás do login.
- O Cloudflare Access da borda **sai de cena** quando esta auth entrar — o app
  fica no domínio borderless (deploy pendente) acessível a qualquer pessoa do
  ecossistema com suas credenciais da plataforma.

---

## 2. Fluxo de login

```
┌─ SPA (Vite) ──────────────┐      ┌─ FastAPI ─────────────────────────┐      ┌─ Plataforma BL ─────┐
│ /login (client)           │      │ POST /auth/login                  │      │                     │
│                           │      │                                   │      │                     │
│ 1. form email+senha ────► │────► │ 2. rate limit 'signin:<email>'    │      │                     │
│                           │      │ 3. POST /api/auth/signin ─────────┼────► │ valida credenciais  │
│                           │      │    x-api-key: <BORDERLESS_AUTH_   │ ◄────┤ 200 { user, token } │
│                           │      │    API_KEY> · timeout 10s         │      │                     │
│ 5. ◄─ { user, accessToken,│ ◄────┤ 4. monta resposta:                │      │                     │
│        isAdmin } ─────────┤      │    user + accessToken + isAdmin   │      │                     │
│                           │      │    (e-mail ∈ ADMIN_EMAILS)        │      │                     │
│ 6. guarda sessão em       │      └───────────────────────────────────┘      └─────────────────────┘
│    localStorage           │
│ 7. router → ?next= ou /   │      Depois do login, toda chamada:
└───────────────────────────┘      Authorization: Bearer <accessToken>
                                   → require_user valida o JWT LOCALMENTE
                                     (assinatura + expiração) e injeta a
                                     identidade no request context.
```

- O bridge roda no FastAPI porque a **key header é segredo de servidor** — nunca
  pode ir para o bundle do SPA.
- Não há refresh na v1 (a plataforma não expôs refresh): token expirado ⇒
  qualquer chamada devolve 401 ⇒ o SPA limpa a sessão e volta ao `/login?next=…`.

---

## 3. Contrato com a plataforma

```
POST {BORDERLESS_AUTH_URL}/api/auth/signin
Content-Type: application/json
x-api-key: <BORDERLESS_AUTH_API_KEY>        # nome exato do header: a confirmar (§9)

{ "email": "...", "password": "..." }
```

Resposta `200 OK`:

```json
{
  "message": "string",
  "data": {
    "user": {
      "id": "string",
      "email": "hello@example.com",
      "name": "string",
      "emailVerified": true,
      "username": "string",
      "careerStage": "junior_transition"
    },
    "token": {
      "accessToken": "string",
      "expiresIn": 1
    }
  }
}
```

Erros (`400 | 401 | 403 | 429 | 500`) vêm como:

```json
{
  "error": {
    "code": "string", "type": "string", "domain": "string",
    "message": "string", "timestamp": "string",
    "details": { "propertyName*": "anything" }
  }
}
```

Mapeamento no bridge (o SPA nunca vê o erro cru):

| Plataforma | Código devolvido ao SPA |
|---|---|
| `429` | `rate-limited` |
| `5xx`, timeout, erro de rede | `unavailable` |
| demais `4xx` (400/401/403) | `invalid-credentials` |

---

## 4. Backend (FastAPI)

### 4.1 Client — `src/support/clients/borderless/borderless_auth_client.py`

`BorderlessAuthClient.sign_in(email, password)`. Integração externa ⇒ Client em
`support/clients` (regra do CLAUDE.md). Obrigatório:

- `timeout` de 10s; sem cache; key header vinda de `Settings`.
- Normalizar `email.strip().lower()` antes de enviar; rejeitar vazios antes da rede.
- Mapear erros conforme §3; **nunca logar senha nem accessToken** (logar só o
  objeto de erro/status).

### 4.2 Subdomínio `src/domain/users/` (enxuto)

- `entities/user.py` — `@dataclass User`: `id`, `email`, `name`, `username`,
  `career_stage`, `email_verified`. Puro, sem SQLAlchemy.
- `actions/sign_in_action.py` — `SignInAction.execute(email, password)`:
  rate limit → client → montar `SignInResult` (user + access_token +
  expires_in + is_admin). Lança exceções de domínio; o controller traduz.
- `dtos/` — `SignInResult` (dataclass interna).
- **Sem `models/`, `repositories/`, `mappers/`**: nada persiste — admin é
  allowlist (§4.4) e a identidade por requisição vem do JWT. Se um dia o oráculo
  precisar de dados próprios por usuário, aí nasce a tabela (fora da v1).

### 4.3 Rate limit durável — `src/support/core/rate_limit/`

Janela fixa em Postgres (tabela `rate_limits`: `key`, `window_start`, `count`),
atualizada num único upsert atômico; migration própria. Uso no login:
`rate_limit(f"signin:{email}", limit=10, window_ms=600_000)` → 10 tentativas por
e-mail a cada 10 minutos.

- **Fail-open**: erro de banco devolve `True` (indisponibilidade transitória do
  Postgres não pode derrubar o login inteiro).
- Em memória **não** serve: multi-worker/serverless reseta e fragmenta o
  contador (lição paga no socratic-dev).

### 4.4 Dependencies — `src/app/api/dependencies/`

- `require_user.py` — lê `Authorization: Bearer`, valida o JWT **localmente**
  (assinatura + `exp`; algoritmo e origem da chave: §9), injeta a identidade
  (`sub`, e-mail) no request context (ContextVar, padrão do projeto). Sem
  header/JWT inválido/expirado ⇒ **401**.
- `require_admin.py` — deixa de ser no-op: exige `require_user` e
  `email ∈ settings.ADMIN_EMAILS`; caso contrário levanta `NotFoundError` ⇒
  **404** (a página de ops não revela que existe — como o comentário atual do
  arquivo já determina). O lado do frontend (`useCurrentUser().isAdmin`) é só UI.

### 4.5 Rotas

- `src/app/api/routes/auth.py` — `public_router`, `POST /auth/login` (única rota
  pública além de health). Controller fino: request schema → `SignInAction` →
  response schema.
- `src/app/api/routes/conversations.py` — deixa de ser pública: `router` com
  dependency `require_user`.
- `src/app/api/routes/ops.py` — dependency `require_admin` (agora real).

### 4.6 Ownership das conversas

`ConversationModel.user_email` já existe (nullable). Com auth:

- `ask` carimba o `user_email` do token na conversa criada.
- `list`/`get` filtram por `user_email` do usuário autenticado; `get` de conversa
  alheia ⇒ **404** (não 403 — não revelar existência).
- Conversas antigas com `user_email` null somem das listagens — **deliberado**
  (eram do período sem auth).

### 4.7 Env novas (`Settings`)

```env
BORDERLESS_AUTH_URL=https://api.borderlesscoding.com
BORDERLESS_AUTH_API_KEY=            # segredo de servidor — NUNCA no frontend
BORDERLESS_JWT_ALGORITHM=           # a confirmar (§9)
BORDERLESS_JWT_PUBLIC_KEY=          # ou BORDERLESS_JWT_SECRET / JWKS_URL — a confirmar (§9)
ADMIN_EMAILS=                       # lista separada por vírgula
```

Validação do JWT exige lib (ex.: `pyjwt`) — **dependência nova, passa pela regra
do `pyproject.toml`** e fica registrada no ADR-0017.

---

## 5. Frontend (SPA)

### 5.1 Sessão

`localStorage` + header `Bearer` (escolha aprovada): API e SPA podem ficar em
hosts distintos do domínio borderless, o SSE já é `fetch` (aceita header) e
evita CSRF de cookie. Chave única no storage com `{ user, accessToken, isAdmin,
expiresAt }`.

### 5.2 `AuthProvider` / `useUser` — três estados, não dois

`{ user, loading, error }` — lição do socratic-dev (§8.1): falha transitória ao
restaurar/validar a sessão é `error` (tela "não foi possível verificar sua
sessão" + retry), **nunca** tratada como deslogado. Só `!user && !error`
redireciona para `/login?next=…`.

### 5.3 Peças

- **`/login`** — formulário e-mail+senha; erros por código traduzido
  (`invalid-credentials`, `rate-limited`, `unavailable`), nunca o erro cru;
  guard de duplo submit; validação do `?next=` (**só paths relativos**:
  `next.startsWith("/") && !next.startsWith("//")`, senão `/`).
- **`RequireAuth`** — envolve o chat (raiz e `/c/:id`); três estados do §5.2.
- **`useCurrentUser`** — deixa de ser placeholder: lê a sessão; `isAdmin` vem do
  login (uso só de UI — quem manda é o 404 do backend).
- **`apiFetch`/SSE** — injetam `Authorization: Bearer`; **qualquer 401 ⇒ limpa a
  sessão ⇒ `/login?next=<rota atual>`** (cobre expiração sem refresh).
- **`AuthSettings`** (rodapé da sidebar, slot já criado) — vira real: e-mail do
  usuário + botão "Sair" (limpa storage, volta ao `/login`).

---

## 6. Segurança

- Key header e validação de JWT só no servidor; senha nunca persiste nem
  aparece em log (nem no SPA, nem no FastAPI).
- Nada de permissão/valor em dados graváveis pelo cliente: `isAdmin` no
  localStorage é UI — o backend recalcula da allowlist a cada request de ops.
- Rate limit no login (§4.3) — protege a plataforma e o bridge.
- `?next=` validado no frontend (open redirect).
- 404 (não 403) para ops sem admin e para conversa de outro usuário.
- CORS: se SPA e API ficarem em hosts distintos, liberar só o domínio do app
  (nada de `*` com credenciais).

## 7. Fora de escopo (v1)

- Refresh de token (a plataforma não expôs; expirar ⇒ logar de novo).
- "Esqueci minha senha" / cadastro — assunto da plataforma.
- Tabela `users` local / perfil próprio do oráculo.
- Roles além de admin-por-allowlist.

## 8. Lições herdadas do socratic-dev que continuam valendo

1. **Três estados no guard do client** (loading / erro transitório / deslogado) —
   sem isso, um erro de rede momentâneo derruba usuário logado para o login.
2. **Rate limit em memória não existe** em multi-worker — Postgres.
3. **Erros por código traduzido**, nunca o erro cru da plataforma na tela.
4. **Open redirect no `?next=`** — validar em todo lugar que o lê.
5. **Nada que valha permissão/dinheiro em storage gravável pelo cliente.**
6. **Nunca logar senha/token** — logar só objeto de erro/status.

## 9. A confirmar com o time (bloqueiam implementação parcial, não o desenho)

| Pendência | Impacto |
|---|---|
| Algoritmo do JWT e origem da chave (pública/JWKS/segredo compartilhado) | implementação do `require_user` |
| Nome exato do header da key de app (`x-api-key`?) e como recebê-la | client do bridge |
| Unidade do `expiresIn` (segundos? horas?) | `expiresAt` no SPA |
| Claims presentes no JWT (`sub`? e-mail? nome?) | o que o request context carrega; se faltar e-mail no token, `require_user` precisa de outra fonte p/ ownership e allowlist |

## 10. Testes

- **Unit (backend):** `SignInAction` (rate limit, mapeamento de erros do client,
  isAdmin da allowlist); `require_user` com JWT forjado (válido, expirado,
  assinatura errada, sem header ⇒ 401); `require_admin` (não-admin ⇒ 404);
  rate limit (janela, fail-open).
- **Integração (backend):** `/conversations/ask` sem token ⇒ 401; com token ⇒
  conversa carimbada com o e-mail; `list` não vaza conversa alheia; `get` de
  conversa de outro usuário ⇒ 404; `/ops` sem admin ⇒ 404.
- **Frontend:** `RequireAuth` três estados; redirect com `?next=` validado;
  `apiFetch` injeta Bearer e trata 401; login traduz códigos de erro;
  `AuthSettings` mostra usuário e sai.

## 11. Checklist de implementação

- [ ] ADR-0017 (plataforma como IdP, JWT local, sem Supabase; registra a dep nova de JWT)
- [ ] Env novas em `Settings` + `.env.example`
- [ ] `BorderlessAuthClient` (timeout, mapeamento de erros, sem log sensível)
- [ ] Migration + `rate_limits` (upsert atômico, fail-open)
- [ ] `src/domain/users/` (entity, `SignInAction`, DTOs)
- [ ] `POST /auth/login` (controller + request/response schemas + rota pública)
- [ ] `require_user` (JWT local) + `require_admin` (allowlist ⇒ 404)
- [ ] `/conversations/*` protegidas + ownership (carimbo e filtro por `user_email`)
- [ ] Frontend: sessão/`AuthProvider`, `/login`, `RequireAuth`, `apiFetch`/SSE com Bearer + 401 global, `AuthSettings` real
- [ ] Testes do §10
- [ ] Desligar Cloudflare Access na borda (após deploy com auth ativa)
- [ ] Atualizar `CLAUDE.md` (auth deixa de ser ponto em aberto)
