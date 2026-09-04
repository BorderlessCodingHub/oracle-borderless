# Autenticação — spec do Oracle Borderless (v2 — BFF)

**Status:** v2 (BFF) **implementada em 2026-09-04** na branch `feat/autenticacao`,
conforme o ADR-0018. O §0 abaixo registra o delta que foi aplicado sobre a v1
(ADR-0017), para leitura histórica; o restante do documento descreve o que o
código faz hoje. Contrato da plataforma verificado em `autenticacao_plataform.md`.

---

## 0. Delta da refatoração (v1 implementada → v2 alvo)

| Peça | v1 (na branch) | v2 (alvo) |
|---|---|---|
| Chamada de signin | com key header | **sem key nenhuma** (login é público) |
| Validação por request | PyJWT local (`require_user`) | `GET /api/users/profile` com o token guardado, **cache 60s** por sessão |
| Onde vive o accessToken | localStorage do SPA (+ Bearer) | **tabela `sessions` no Postgres**; nunca chega ao browser |
| Credencial SPA→oráculo | `Authorization: Bearer <token plataforma>` | **cookie httpOnly próprio** (`ob_session`) |
| Restore de sessão no SPA | ler localStorage | `GET /auth/me` (cookie vai junto; 200 = user, 401 = deslogado) |
| Logout | limpar localStorage | `POST /auth/logout` → signout na plataforma + apaga sessão + limpa cookie |
| Erros da plataforma | mapeados por status | mapeados por **`error.type`** (§3); `403 FORBIDDEN` **repassa a `message`** |
| Envs | `BORDERLESS_AUTH_API_KEY`, `KEY_HEADER`, `JWT_ALGORITHM`, `JWT_VERIFY_KEY` | **todas morrem**; sobram `BORDERLESS_AUTH_URL`, `ADMIN_EMAILS`, `CORS_ORIGINS` |
| Dependência `pyjwt` | usada no require_user | **removida** do pyproject (ADR-0018 registra) |
| Subdomínio `users/` | sem persistência | ganha **model/repository/mapper de Session** (o "se um dia precisar" chegou) |
| Rate limit do login | 10/10min por e-mail | **mantido igual** — ainda mais importante: o limite da plataforma (100 req/min) é por IP, e no BFF todas as chamadas saem do IP do oráculo |
| `tests/fakes/auth.py` (forja JWT) | forja HS256 | vira **fixture de sessão** (semeia linha em `sessions` + cookie) |
| Frontend `session.ts`/`authHeaders` | localStorage + Bearer + memorySession | **removidos**; fetch same-origin leva o cookie sozinho |
| RequireAuth 3 estados | erro só se storage bloqueado | **ganham uso real**: falha de rede no `/auth/me` = "error" + retry (a lição §8.1 do socratic-dev finalmente se aplica de verdade) |

O que **não muda**: bridge no FastAPI; 401 genérico único; `/ops` por allowlist
`ADMIN_EMAILS` com 404; ownership de conversas por e-mail com 404 (órfãs somem);
enforcement mecânico de auth no autodiscovery de rotas; página `/login` com
`?next=` validado; códigos de erro traduzidos no SPA.

---

## 1. O modelo em uma frase

**As credenciais vivem na plataforma Borderless e o `accessToken` dela — opaco, 7
dias, acesso total à conta — nunca sai do servidor do oráculo.** O FastAPI é um
**BFF**: no login ele chama o signin da plataforma, guarda o `accessToken` numa
linha de `sessions` e devolve ao browser um **cookie httpOnly** com um token de
sessão próprio. A cada request, `require_user` resolve o cookie → sessão → valida
o token da plataforma via `GET /api/users/profile` (com cache de 60s) — assim
banimento/revogação na plataforma refletem em até um minuto.

---

## 2. Fluxos

### Login

```
┌─ SPA ────────────────┐   ┌─ FastAPI (BFF) ─────────────────────┐   ┌─ Plataforma ────────┐
│ /login: email+senha ─┼──►│ POST /auth/login                    │   │                     │
│                      │   │ 1. rate limit 'signin:<email>'      │   │                     │
│                      │   │ 2. POST /api/auth/signin ───────────┼──►│ (público, sem key)  │
│                      │   │ ◄─── 200 { user, token } ───────────┼───┤ accessToken opaco   │
│                      │   │ 3. cria linha em sessions           │   │ expiresIn: 604800   │
│                      │   │    (hash do token nosso +           │   │                     │
│                      │   │     accessToken da plataforma)      │   │                     │
│ ◄─ 200 {user,isAdmin}│◄──┤ 4. Set-Cookie: ob_session=<token>;  │   │                     │
│    + cookie httpOnly │   │    HttpOnly; SameSite=Lax; Path=/   │   │                     │
└──────────────────────┘   └─────────────────────────────────────┘   └─────────────────────┘
```

### Request autenticada

```
SPA ──(cookie ob_session vai sozinho no fetch same-origin)──► FastAPI
  require_user: cookie → SHA-256 → sessions → sessão achada?
    ├─ não/expirada ⇒ 401 (SPA limpa estado e vai p/ /login?next=…)
    └─ sim ⇒ last_platform_check_at < 60s?
        ├─ sim ⇒ segue (cache)
        └─ não ⇒ GET /api/users/profile (Bearer <accessToken da sessão>)
            ├─ 200 ⇒ atualiza last_platform_check_at, segue
            ├─ 401 ⇒ apaga a sessão ⇒ 401 (revogada/expirada na plataforma)
            └─ rede/5xx ⇒ **fail-open dentro da janela estendida**: se a última
               validação OK tem < 10min, segue com log; senão 503 "unavailable"
               (não derrubar todo mundo por um soluço da plataforma, sem deixar
               sessão validar-se sozinha para sempre)
  ⇒ AuthenticatedUser(id, email, is_admin=email ∈ ADMIN_EMAILS) no request context
```

### Restore, logout e expiração

- **Restore (reload do SPA):** `GET /auth/me` → 200 `{user, is_admin}` ou 401. O
  cookie é httpOnly — o SPA não tem como ler; `/auth/me` é a única fonte.
- **Logout:** `POST /auth/logout` → best-effort `POST /api/auth/signout` na
  plataforma (invalida lá — descartar só localmente deixa a sessão viva),
  apaga a linha de `sessions`, `Set-Cookie` expirado. **Sempre 204**, mesmo se
  a plataforma falhar (o log registra) ou se não houver cookie. A rota é
  **pública** (autentica pelo hash do próprio cookie): precisa funcionar quando
  o `require_user` responderia 503/401, senão o cookie sobrevive e o usuário
  reaparece logado quando a plataforma volta.
- **Expiração:** a plataforma renova a sessão conforme o uso (janela de 7 dias
  deslizante); o cookie acompanha — `GET /auth/me` (todo boot do SPA) o reemite
  com Max-Age cheio. Sem refresh token: o primeiro `401`/`403` da plataforma
  apaga a sessão local (o 401 do oráculo já leva o `Set-Cookie` que apaga o
  cookie) e o SPA volta ao `/login?next=…`. Não há expiração local própria — a
  plataforma é a fonte da verdade do ciclo de vida. **Faxina:** o
  `PurgeStaleSessionsJob` (diário) apaga linhas sem validação há mais de 7 dias
  — a plataforma já as expirou por inatividade; sem isso a tabela cresceria sem
  limite guardando tokens mortos.

---

## 3. Contrato com a plataforma (verificado — `autenticacao_plataform.md`)

### `POST /api/auth/signin` — público, sem key

Request `{ "email", "password" }` (a API normaliza o e-mail; senha mínima 6).
Resposta 200: `data.user {id, email, name?, emailVerified, username, careerStage?}`
e `data.token {accessToken, expiresIn: 604800}` (fixo, 7 dias).

### `GET /api/users/profile` — validação + autorização

`Authorization: Bearer <accessToken>`. 200 = sessão válida (devolve também
`membership` e `communityRole` — ver §8); 401 = expirada/revogada. **Não enviar
cookie junto com Authorization.**

### `POST /api/auth/signout`

`Authorization: Bearer <accessToken>`. Invalida a sessão na plataforma.

### Erros — mapear por `error.type` (campo estável), nunca por `message`

| `error.type` (status) | Código devolvido ao SPA | Observação |
|---|---|---|
| `VALIDATION` (400), `UNAUTHORIZED` (401) | `invalid-credentials` (401) | |
| `FORBIDDEN` (403) | `forbidden` (403) **com a `message` da API** | é o único caso em que a mensagem da plataforma vai à tela — ela distingue desativado/banido/convite pendente |
| `TOO_MANY_REQUESTS` (429) | `rate-limited` (429) | backoff, nunca retry em loop |
| `INTERNAL` (500), timeout, rede, corpo fora do contrato | `unavailable` (503) | |

O envelope de erro é `{"error": {"code", "type", "domain", "message", "timestamp",
"details"}}`. Docs completas: `https://api.borderlesscoding.com/api/docs`.

---

## 4. Backend (FastAPI)

### 4.1 Tabela e subdomínio — `sessions` nasce em `src/domain/users/`

Agora há persistência: entity `UserSession` (dataclass pura), `UserSessionModel`
(SQLAlchemy), `UserSessionMapper`, `UserSessionRepository` — o padrão completo do
CLAUDE.md (prefixo `User` para não colidir com a `AsyncSession` do SQLAlchemy que
os repositórios já chamam de `self.session`). Migration `0009_sessions`. A
resolução cookie → sessão → validação vive na `ResolveSessionAction`.

Colunas de `sessions`:

- `uuid` (HasUUID) + timestamps (HasTimestamps)
- `token_hash` — SHA-256 do token de sessão do oráculo, **unique, indexed**. O
  token cru (`secrets.token_urlsafe(32)`) só existe no cookie; o banco guarda o
  hash (vazamento de dump não vira sessão).
- `platform_access_token` — o accessToken da Borderless (opaco). Fica em claro na
  nossa base (é o BFF; cifrar aqui só mudaria o problema de lugar para a chave).
- `user_id`, `user_email`, `user_name`, `user_username` — snapshot do login para
  `/auth/me` sem ida à rede.
- `last_platform_check_at` — o cache de validação (§2).

`is_admin` **não** persiste: computado por request de `settings.admin_emails`
(mudar a allowlist vale imediatamente).

### 4.2 Client — `BorderlessAuthClient` (reescrito)

- `sign_in(email, password) -> PlatformSignIn` — **sem key header**; mapeia erros
  por `error.type` (§3). `FORBIDDEN` vira exceção nova `ForbiddenError(message)`
  carregando a mensagem da plataforma.
- `get_profile(access_token) -> PlatformProfile | None` — `None`/exceção
  distinguindo 401 (inválida) de erro de rede (para o fail-open do §2).
- `sign_out(access_token) -> None` — best-effort, engole erro com log.
- Mantém: timeout 10s, nunca logar senha/token, e-mail normalizado.

### 4.3 Actions (`src/domain/users/actions/`)

- `SignInAction.execute(email, password) -> SignInResult` — rate limit (igual v1)
  → `client.sign_in` → cria `Session` via repository (gera token cru + hash) →
  devolve `SignInResult(user, session_token_cru, is_admin)`. O token cru **não é
  logado nem persistido** — só atravessa até o Set-Cookie.
- `SignOutAction.execute(session: Session)` — signout na plataforma (best-effort)
  + `repository.delete`.
- `GetCurrentUserAction` fica dispensável: `/auth/me` lê do `AuthenticatedUser` do
  contexto + snapshot da sessão (controller fino chama uma action só se houver
  lógica; se for só projeção, response schema direto do contexto).

### 4.4 `require_user` (reescrito) e `require_admin` (igual)

`require_user`: lê o cookie `ob_session` (sem cookie ⇒ 401 genérico) → hash →
`SessionRepository.get_by_token_hash` (miss ⇒ 401) → validação com cache/fail-open
do §2 → injeta `AuthenticatedUser` no `CurrentRequestContext`. O 401 continua
único e indistinguível. `require_admin` não muda (allowlist ⇒ 404).

**Cookie:** `ob_session`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` quando
`ENVIRONMENT != development`, `Max-Age` 7 dias. **CSRF:** SameSite=Lax bloqueia
POST cross-site; o oráculo não usa CORS com credenciais. **Pré-requisito de
deploy: SPA e API no MESMO host** (path routing) — split-host exigiria
`SameSite=None` + CSRF token, que está fora da v2 (registrar no §8 se o deploy
apontar para split-host).

### 4.5 Rotas

- `auth.py` (`public_router`): `POST /auth/login` e `POST /auth/logout` (ver §2:
  o logout se autentica pelo hash do cookie e não pode depender do guard).
  **`GET /auth/me` fica no `router`** (autodiscovery aplica `require_user`
  mecanicamente — nada a fazer).
- `/conversations/*` e `/ops/*`: sem mudança (a identidade continua vindo do
  contexto; só a origem dela mudou).

### 4.6 Envs

Morrem: `BORDERLESS_AUTH_API_KEY`, `BORDERLESS_AUTH_KEY_HEADER`,
`BORDERLESS_JWT_ALGORITHM`, `BORDERLESS_JWT_VERIFY_KEY`. Ficam:
`BORDERLESS_AUTH_URL`, `ADMIN_EMAILS`, `CORS_ORIGINS` (segue existindo para o
caso same-site com subdomínios; irrelevante no same-host). Novas: nenhuma
obrigatória (`SESSION_PLATFORM_CHECK_TTL_S=60` e `SESSION_FAIL_OPEN_MAX_S=600`
podem ser constantes; virar env só se precisarmos calibrar).

**Dev funciona sem nenhum segredo**: basta a plataforma estar acessível e um
usuário real de teste (§8).

---

## 5. Frontend (SPA)

- **Morre**: `lib/auth/session.ts` (localStorage/memorySession), `authHeaders()`,
  qualquer menção a Bearer. O cookie viaja sozinho (`fetch` same-origin envia
  cookies por padrão; não é preciso `credentials` explícito no same-host).
- **`useAuth`**: `login()` chama `POST /auth/login` (o Set-Cookie acontece na
  resposta) e guarda `{user, isAdmin}` **só em memória/estado React**; restore =
  `GET /auth/me` no boot — 200 popula, 401 = deslogado, **falha de
  rede/5xx = status "error" com retry** (os três estados do RequireAuth agora têm
  o caso real que motivou o desenho). `logout()` chama `POST /auth/logout` e
  zera o estado.
- **Códigos de erro do login**: os três existentes + **`forbidden`** — neste
  caso a resposta do backend traz a mensagem da plataforma e o SPA a exibe
  (única exceção à regra "nunca o erro cru": é mensagem voltada a usuário,
  contrato do doc da plataforma).
- **401 global**: igual (limpa estado → `/login?next=…`), só que sem storage a
  limpar.
- **Demo mode**: igual (sessão fake em memória, sem rede).

---

## 6. Segurança

- accessToken da plataforma **nunca** no browser, em log ou em resposta de API.
- Cookie httpOnly + SameSite=Lax + Secure (fora de dev); token de sessão em hash
  no banco.
- 401 único e genérico; 404 (nunca 403) para ops sem admin e conversa alheia —
  **exceto** o `forbidden` do login, que deliberadamente repassa a mensagem.
- Rate limit próprio no login preserva o limite compartilhado por IP da
  plataforma.
- Validação com cache de 60s: banimento/revogação refletem em ≤60s; fail-open
  limitado a 10min de última validação boa.

## 7. Fora de escopo (v2)

Signup, reset de senha (endpoints da plataforma; não duplicar), gate de conteúdo
por `membership`/entitlements (§8), sessões multi-dispositivo gerenciáveis,
CSRF token para split-host.

## 8. Pendências com o time Borderless (do checklist §9 do doc da plataforma)

| Pendência | Impacto |
|---|---|
| Usuário de teste em staging | destrava validação manual do contrato (passo 1 do doc) |
| `emailVerified: false` pode usar o oráculo? | se não: bloquear no login com código próprio |
| `membership` basta ou precisa endpoint de entitlements? | só se o oráculo for gatear conteúdo por plano (hoje não gateia) |
| Rate limit 100 req/min por IP é suficiente? | o BFF concentra todas as chamadas num IP; com cache de 60s por sessão a pressão é ~1 req/min/usuário ativo + logins |
| **CORS na plataforma: NÃO precisa** | o browser nunca fala com a plataforma no BFF — retirar o pedido de `CORS_EXTRA_ORIGINS` se foi feito |

## 9. O que remover da v1 (checklist de limpeza)

- [x] `pyjwt[crypto]` do `pyproject.toml` (e do ADR — o 0018 registra)
- [x] Validação JWT em `require_user.py` (o arquivo é reescrito, não deletado)
- [x] Envs `BORDERLESS_AUTH_API_KEY/KEY_HEADER/JWT_*` de `Settings` e `.env.example`
- [x] Key header no `BorderlessAuthClient`
- [x] `tests/fakes/auth.py` (forja JWT) → substituir por fixture de sessão
- [x] `frontend/src/lib/auth/session.ts`, `authHeaders()`/Bearer no `client.ts` e
      no `askStream`, e os testes correspondentes
- [x] §5.1 antigo do spec (localStorage) — este documento já o substitui

## 10. Testes (delta)

- **Unit:** client novo (signin sem key, erros por `type`, `FORBIDDEN` carrega
  message; get_profile 200/401/rede; signout best-effort); `SignInAction` v2
  (cria sessão, token cru não persiste); `require_user` (sem cookie/cookie
  inválido ⇒ 401; cache de 60s não chama a plataforma; 401 da plataforma apaga
  sessão; fail-open dentro/fora da janela).
- **Integração:** login seta cookie e cria linha; `/auth/me` com/sem cookie;
  `/conversations` com cookie válido/ausente; logout apaga sessão e invalida o
  cookie nas chamadas seguintes; ownership/ops inalterados (só trocam o header
  Bearer forjado pela fixture de cookie).
- **Frontend:** useAuth restore via `/auth/me` (200/401/erro de rede — os três
  estados); login `forbidden` mostra a mensagem; logout; 401 global sem storage.

## 11. Checklist de implementação (ordem sugerida)

- [ ] Validar o contrato manualmente (curl do §3 com usuário de teste) — passo 1
      do doc da plataforma; destrava tudo
- [x] ADR-0018 já escrito — revisar e manter
- [x] Migration + Session (entity/model/mapper/repository)
- [x] `BorderlessAuthClient` v2 + exceção `ForbiddenError` + handler (403 com message)
- [x] `SignInAction` v2 + `SignOutAction`
- [x] `POST /auth/login` (Set-Cookie) + `GET /auth/me` + `POST /auth/logout`
- [x] `require_user` v2 (cookie → sessão → cache/fail-open)
- [x] Limpeza da v1 (§9) + fixtures de teste novas
- [x] Frontend: useAuth v2 (restore /me), remoção do session.ts/Bearer, forbidden
- [x] CLAUDE.md: linha da stack de auth passa a descrever o BFF (fazer NO commit
      da implementação — hoje ela descreve a v1, que é o que o código da branch faz)
- [x] Suíte completa + prospector + build
