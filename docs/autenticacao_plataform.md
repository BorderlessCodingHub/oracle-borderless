# Integração de autenticação — aplicações externas

Guia para conectar uma aplicação externa à base de usuários da Borderless usando o
endpoint de login da `borderless-api`.

**Público:** time de desenvolvimento da aplicação externa.
**API:** `https://api.borderlesscoding.com`
**Status deste documento:** todo comportamento descrito aqui foi verificado no código
da `borderless-api` (referências de arquivo/linha ao final). Os pontos que dependem de
decisão ou ação do time Borderless estão marcados com ⚠️.

---

## 1. Modelo mental (leia antes de implementar)

A Borderless usa **Better Auth** com sessões persistidas em banco. O login devolve um
**token de sessão opaco** — **não é um JWT**.

Isso tem três consequências práticas que definem a arquitetura da integração:

1. **Você não consegue validar o token localmente.** Não há assinatura, não há
   algoritmo (RS256/HS256) e não há chave pública. Não existe `iss`, `exp` ou `sub`
   para ler. Qualquer verificação exige uma chamada à `borderless-api`.
2. **A Borderless continua sendo a fonte da verdade.** Se o usuário for desativado,
   banido ou tiver a sessão revogada, isso reflete na próxima chamada — porque toda
   chamada revalida a sessão contra o banco.
3. **Não existe refresh token.** Não há endpoint de renovação. Quando a sessão expira,
   o usuário refaz o login.

Não tente implementar verificação de JWT, `jwks`, chave pública PEM ou algoritmo de
assinatura. Nada disso existe nesta API.

---

## 2. Endpoint de login

```
POST https://api.borderlesscoding.com/api/auth/signin
Content-Type: application/json
```

### Request

| Campo      | Tipo   | Obrigatório | Regras                                    |
| ---------- | ------ | ----------- | ----------------------------------------- |
| `email`    | string | ✅          | Normalizado pela API (trim + lowercase)   |
| `password` | string | ✅          | Mínimo de 6 caracteres                    |

```bash
curl https://api.borderlesscoding.com/api/auth/signin \
  --request POST \
  --header "Content-Type: application/json" \
  --data '{
    "email": "usuario@exemplo.com",
    "password": "senha-do-usuario"
  }'
```

**O login é público — não exige API key, header proprietário nem credencial de
aplicação.** Os únicos headers necessários são os do exemplo acima. Ver §7 para o
esclarecimento sobre o "key header" mencionado na explicação inicial.

### Response `200 OK`

```json
{
  "message": "Sign in successful",
  "data": {
    "user": {
      "id": "string",
      "email": "usuario@exemplo.com",
      "name": "string",
      "emailVerified": true,
      "username": "string",
      "careerStage": "junior_transition"
    },
    "token": {
      "accessToken": "string",
      "expiresIn": 604800
    }
  }
}
```

Observações sobre o payload:

- `expiresIn` é sempre `604800` (7 dias em segundos). É um valor fixo na resposta, não
  um cálculo por sessão.
- `name` e `careerStage` são opcionais — trate como possivelmente ausentes.
- `emailVerified` indica se o usuário confirmou o e-mail. Decida com o time se a
  aplicação externa deve bloquear usuários não verificados.
- **A resposta não inclui plano/assinatura.** Se a aplicação externa precisa liberar
  conteúdo por tier (`FREE`, `STARTER`, `BASE`, `PSP`), veja §4.

### Erros

Todos os erros usam o mesmo envelope:

```json
{
  "error": {
    "code": "AUTH-UNAUTHORIZED-401",
    "type": "UNAUTHORIZED",
    "domain": "AUTH",
    "message": "Invalid credentials",
    "timestamp": "2026-09-04T12:00:00.000Z",
    "details": {}
  }
}
```

O `code` segue o formato `DOMAIN-TYPE-STATUS`. Use `error.type` para lógica de
programa — é o campo estável. Não faça parsing de `error.message`; ele é texto voltado
ao usuário e pode mudar.

| Status | `type`              | Quando acontece                                          | O que a aplicação deve fazer                         |
| ------ | ------------------- | -------------------------------------------------------- | ---------------------------------------------------- |
| `400`  | `VALIDATION`        | E-mail inválido ou senha com menos de 6 caracteres        | Mostrar erro no formulário                           |
| `401`  | `UNAUTHORIZED`      | Credenciais inválidas                                     | "E-mail ou senha incorretos"                         |
| `403`  | `FORBIDDEN`         | Conta desativada, banida ou com convite pendente          | Mostrar a `message` da API — ela explica o caso       |
| `429`  | `TOO_MANY_REQUESTS` | Rate limit (padrão: 100 req/min por IP)                   | Backoff; nunca retry imediato em loop                |
| `500`  | `INTERNAL`          | Falha no servidor                                         | Mensagem genérica + log com `timestamp`              |

O `403` cobre casos distintos com mensagens diferentes (desativado, banido, convite
pendente). Repassar a `message` da API é o comportamento correto aqui.

---

## 3. Chamadas autenticadas depois do login

Envie o `accessToken` no header `Authorization`:

```bash
curl https://api.borderlesscoding.com/api/users/profile \
  --header "Authorization: Bearer <accessToken>"
```

Duas regras importantes:

- **Não envie cookie junto com `Authorization`.** Quando o header `authorization` está
  presente, a API descarta o header `cookie` antes de resolver a sessão. Mandar os dois
  não é ambíguo, mas é ruído — use só o Bearer.
- **Toda chamada autenticada revalida no banco.** Não há cache de sessão do lado da
  aplicação externa que seja seguro assumir.

### Ciclo de vida da sessão

- Duração: **7 dias**.
- A sessão é **renovada conforme o uso** — a API atualiza a expiração no máximo a cada
  5 minutos de atividade. Um usuário ativo não é deslogado no sétimo dia; um usuário
  inativo por 7 dias é.
- **Sem refresh token.** Ao receber `401` em qualquer chamada, descarte o token local e
  redirecione para o login.

### Logout

```
POST https://api.borderlesscoding.com/api/auth/signout
Authorization: Bearer <accessToken>
```

Invalida a sessão no lado da Borderless. Chame sempre no logout da aplicação externa —
descartar o token só localmente deixa a sessão viva na plataforma.

---

## 4. Validar o token e obter o plano do usuário

Use o endpoint de perfil autenticado:

```
GET https://api.borderlesscoding.com/api/users/profile
Authorization: Bearer <accessToken>
```

Ele serve para dois propósitos: **validar que a sessão ainda é válida** (`200` = válida,
`401` = expirada/revogada) e **obter os dados de autorização** que o login não devolve.

Response `200`:

```json
{
  "data": {
    "user": {
      "id": "string",
      "name": "string",
      "email": "usuario@exemplo.com",
      "image": null,
      "username": "string",
      "communityRole": "MEMBER",
      "membership": "BASE",
      "seniority": null,
      "location": null,
      "linkedin": null,
      "github": null,
      "instagram": null,
      "discord": null,
      "isShowEmail": false,
      "hasPassword": true,
      "authProviders": [],
      "careerStage": "junior_transition",
      "emailPlatformSubscribed": true,
      "emailEditorialSubscribed": true,
      "emailPromoSubscribed": true,
      "newsletterSubscribedAt": null,
      "emailPreferencesUpdatedAt": null,
      "emailAudienceSyncStatus": "..."
    }
  }
}
```

Os campos que interessam para autorização:

- `membership` — tier de assinatura: `FREE`, `STARTER`, `BASE`, `PSP`. **É opcional na
  resposta**; trate a ausência como sem assinatura ativa.
- `communityRole` — papel na comunidade: `AMBASSADOR`, `BUILDER`, `PSP`, `BASE`,
  `MEMBER`.

⚠️ **Se a aplicação externa for liberar conteúdo por plano, alinhe com o time Borderless.**
`membership` reflete a assinatura, mas a plataforma tem um motor de entitlements mais
granular (regras `ALLOW`/`DENY` por recurso, onde `DENY` sempre vence). Ler só o
`membership` é uma aproximação — pode divergir do que a plataforma de fato libera.
Confirme se essa aproximação é aceitável para o caso de vocês ou se é preciso expor um
endpoint de entitlements.

A documentação completa da API (OpenAPI) está em `https://api.borderlesscoding.com/api/docs`.

---

## 5. Arquitetura recomendada: BFF

**Recomendação: a aplicação externa deve chamar o login pelo seu próprio backend, não
direto do browser.**

```
Browser  ──POST /login (credenciais)──▶  Backend da app externa
                                              │
                                              ├──POST /api/auth/signin──▶  borderless-api
                                              │◀──── user + accessToken ────
                                              │
         ◀── Set-Cookie: sessão httpOnly ─────┘
                (accessToken guardado no servidor)
```

Três motivos concretos, em ordem de peso:

1. **Evita o bloqueio de CORS.** A `borderless-api` só aceita requisições de browser
   vindas de origens em allowlist. Requisições sem `Origin` — isto é, server-to-server —
   são sempre aceitas. Com BFF, o problema da §6 simplesmente não existe.
2. **Mantém o token fora do browser.** O `accessToken` dá acesso total à conta na
   Borderless por 7 dias. Guardá-lo em `localStorage` o expõe a qualquer XSS na
   aplicação externa. No BFF ele nunca chega ao cliente.
3. **Desacopla o ciclo de sessão.** A aplicação externa controla a própria sessão
   (duração, logout, renovação) e trata o token da Borderless como credencial de
   backend.

**Se o login for chamado direto do browser**, a §6 vira pré-requisito obrigatório e o
armazenamento do token precisa ser decidido explicitamente (`localStorage` é o padrão
mais comum e o mais arriscado).

---

## 6. ⚠️ CORS — ação necessária antes de ir para produção

**Só se aplica se a aplicação externa chamar a API direto do browser.** Com BFF (§5),
pule esta seção.

A `borderless-api` valida a origem contra uma allowlist. Hoje ela contém apenas:

- `FRONTEND_URL` (plataforma)
- `ADMIN_FRONTEND_URL` (admin)
- `BETTER_AUTH_URL` (a própria API)
- `https://platform-staging.borderlesscoding.com`
- `https://platform-admin-staging.borderlesscoding.com`
- o que estiver em `CORS_EXTRA_ORIGINS`

O domínio da nova aplicação **não está nessa lista**. Enquanto não estiver, toda
chamada feita do browser falha no preflight — inclusive o login.

**O que pedir ao time Borderless:** adicionar a origem da nova aplicação à variável de
ambiente `CORS_EXTRA_ORIGINS` da `borderless-api` (aceita lista separada por vírgula ou
espaço). Isso vale para **cada ambiente** — dev, staging e produção têm origens
diferentes e cada uma precisa ser incluída no ambiente correspondente.

Dois detalhes que costumam morder:

- **Headers permitidos são fixos:** `Content-Type`, `Authorization` e
  `x-captcha-response`. Qualquer header customizado — incluindo um `x-api-key` — é
  rejeitado no preflight. Se a integração precisar de um header proprietário, ele
  precisa ser adicionado à config de CORS da API primeiro.
- **`CORS_EXTRA_ORIGINS` não está no `.env.example` nem no schema Zod de validação**
  (`env.config.ts`). É lida direto de `process.env`. Ou seja: se for escrita errada, o
  boot da API não reclama — a origem simplesmente continua bloqueada. Vale testar o
  preflight depois do deploy.

---

## 7. Sobre o "key header de autorização"

A explicação inicial mencionava passar "um key header de autorização" no endpoint de
login. Esclarecendo, porque isso mudou a implementação esperada:

**Não existe API key nem header proprietário nesta API.** Não há nenhum mecanismo de
chave de aplicação no código da `borderless-api` — nem no login, nem em rota alguma.
O `curl` de referência compartilhado pelo próprio time confirma: só `Content-Type`.

A leitura correta é que o "key header de autorização" é o header **`Authorization:
Bearer <accessToken>`**, usado nas chamadas **depois** do login (§3) — não uma
credencial enviada **no** login.

Consequência prática: **nada de `BORDERLESS_AUTH_API_KEY`, `BORDERLESS_AUTH_KEY_HEADER`,
`BORDERLESS_JWT_ALGORITHM` ou `BORDERLESS_JWT_VERIFY_KEY`** nas variáveis de ambiente da
aplicação externa. Nenhuma dessas tem contrapartida na API.

⚠️ Se a intenção era mesmo ter uma API key de aplicação no login, isso é **feature
nova** na `borderless-api` — precisa ser especificada e construída, não configurada.
Confirmar com o tech lead antes de seguir.

---

## 8. Passo a passo de implementação

Sequência sugerida, na ordem em que cada passo destrava o próximo:

1. **Validar o contrato manualmente.** Rode o `curl` da §2 com um usuário real de
   teste. Confirme o `200` e guarde o `accessToken`.
2. **Validar a chamada autenticada.** Rode o `GET /api/users/profile` da §4 com esse
   token. Confirme que `membership` vem preenchido como esperado.
3. **Decidir a arquitetura** — BFF (§5) ou chamada direta do browser. Essa decisão
   define se o passo 4 é necessário.
4. **(Só para chamada direta do browser)** Abrir a solicitação de CORS com o time
   Borderless (§6) para dev, staging e produção. Trate como pré-requisito de deploy.
5. **Implementar o login** no backend da aplicação externa: recebe e-mail/senha, chama
   `/api/auth/signin`, trata os cinco status de erro da §2.
6. **Implementar a sessão local:** guardar o `accessToken` server-side, associado à
   sessão própria da aplicação (cookie `httpOnly`, `Secure`, `SameSite=Lax`).
7. **Implementar o middleware de autorização:** em rotas protegidas, usar o
   `accessToken` para chamar a Borderless e checar `membership`/`communityRole`.
   Considere cache curto (30–60s) para não gerar uma chamada externa por request — mas
   nunca cache de longa duração, senão banimentos e cancelamentos demoram a refletir.
8. **Implementar o logout:** chamar `POST /api/auth/signout` **e** destruir a sessão
   local.
9. **Tratar expiração:** qualquer `401` vindo da Borderless derruba a sessão local e
   manda para o login. Não há refresh.

### O que a aplicação externa **não** deve implementar

- Cadastro próprio de usuários — a base é a da plataforma. Se precisar de signup,
  existe `POST /api/auth/signup` na Borderless; alinhe antes, porque isso cria usuário
  na plataforma de verdade.
- Reset de senha próprio — use os endpoints `/api/auth/forget-password` e
  `/api/auth/reset-password` da Borderless, para a senha não divergir entre os sistemas.
- Qualquer validação local de token (§1).

---

## 9. Checklist para o time Borderless

- [ ] Adicionar as origens da nova aplicação (dev, staging, produção) em
      `CORS_EXTRA_ORIGINS` — **apenas se a app chamar a API direto do browser** (§6)
- [ ] Confirmar se `membership` é suficiente para o gate de conteúdo ou se é preciso um
      endpoint de entitlements (§4)
- [ ] Confirmar se usuários com `emailVerified: false` podem acessar a aplicação externa
- [ ] Confirmar se o rate limit padrão (100 req/min por IP) é adequado ao volume
      esperado — com BFF, todas as chamadas saem do mesmo IP e o limite é compartilhado
- [ ] Confirmar se a intenção era realmente uma API key de aplicação no login (§7); se
      sim, especificar como feature nova
- [ ] Fornecer credenciais de um usuário de teste em staging

---

## 10. Referências no código (`borderless-api`)

| Assunto                                | Arquivo                                     |
| -------------------------------------- | ------------------------------------------- |
| Rota `POST /signin`                    | `src/routes/api/auth.routes.ts:62`          |
| Prefixo `/api/auth`                    | `src/routes/index.ts:42`                    |
| Schema do request de login             | `src/models/auth.model.ts:12`               |
| Schema da response de login            | `src/models/auth.model.ts:28`               |
| Origem do `accessToken`                | `src/services/auth.service.ts:211`          |
| Config do Better Auth (sessão, bearer) | `src/auth.ts:76` e `src/auth.ts:428`        |
| Resolução da sessão via Bearer         | `src/services/session-auth.service.ts:88`   |
| Guard de rotas protegidas              | `src/plugins/internal/session.ts:75`        |
| Allowlist de CORS e headers            | `src/plugins/external/cors.ts`              |
| Política de origem / `CORS_EXTRA_ORIGINS` | `src/utils/origin-policy.ts`             |
| Rate limit                             | `src/plugins/external/rate-limit.ts`        |
| Envelope de erro                       | `src/errors/app-error.ts`                   |
| Perfil do usuário autenticado          | `src/routes/api/user.routes.ts:69`          |
