# ADR-0018 — Auth vira BFF: token opaco da plataforma vive só no servidor

## Status

Aceito — 2026-09-04. Substitui o **mecanismo de validação e de sessão** do
ADR-0017 (o restante do 0017 — plataforma como IdP, bridge no FastAPI, allowlist
de admin, sem Supabase — permanece válido).

## Resumo

- **Decisão:** o `accessToken` da plataforma é um token de sessão **opaco** do
  Better Auth (não-JWT, sem validação local possível) com acesso total à conta
  por 7 dias — por isso ele **nunca sai do servidor**. O FastAPI vira **BFF**:
  guarda o token numa tabela `sessions` (Postgres), dá ao SPA um cookie httpOnly
  próprio (`ob_session`, SameSite=Lax) e valida a sessão contra
  `GET /api/users/profile` com cache de 60s (fail-open limitado a 10min de
  última validação boa). Login é público (sem key de app); `pyjwt` sai do
  projeto.
- **Aplica-se quando:** qualquer mudança em login/logout/sessão/`require_user`,
  no armazenamento de tokens, no cookie, ou em como o SPA restaura identidade
  (`GET /auth/me`).
- **Regra prática:** nenhum token da plataforma em resposta de API, log ou
  browser; identidade continua vindo de `CurrentRequestContext.get_user()`;
  validação de sessão SEMPRE pela plataforma (nunca local); SPA e API no mesmo
  host (SameSite=Lax é a proteção CSRF — split-host exige redesenho).

---

## Contexto

O ADR-0017 assumiu, a partir do contrato preliminar, que (a) o signin exigia uma
key de app e (b) o `accessToken` era um JWT verificável localmente. O documento
`autenticacao_plataform.md` (04/09/2026, verificado no código da `borderless-api`
pelo tech lead) mostrou que ambas as premissas eram falsas: o login é público, e
o token é uma sessão opaca do Better Auth persistida em banco — sem assinatura,
sem claims, sem chave pública. Toda validação exige chamada à plataforma, e o
token dá acesso total à conta por 7 dias (janela deslizante), sem refresh.

Com validação local impossível, restavam dois desenhos: o SPA continuar
guardando o token (localStorage + Bearer, validação remota no backend) ou o BFF
recomendado pelo próprio doc da plataforma (§5). O dono do produto escolheu o
BFF em 04/09/2026.

## Decisão

1. **BFF**: `POST /auth/login` chama o signin (público), persiste o
   `accessToken` em `sessions` (subdomínio `users/` ganha model/repository/
   mapper) e devolve cookie httpOnly com token de sessão próprio (aleatório;
   no banco só o SHA-256).
2. **Validação por request**: cookie → sessão → `GET /api/users/profile` com o
   token guardado, cacheada por 60s por sessão; 401 da plataforma apaga a
   sessão; falha de rede/5xx segue até 10min da última validação boa, depois
   503.
3. **Logout** chama `POST /api/auth/signout` (best-effort) além de apagar a
   sessão local — descartar só localmente deixaria a sessão viva na plataforma.
4. **Erros do signin mapeados por `error.type`** (campo estável); `FORBIDDEN`
   repassa a `message` da plataforma ao usuário (única exceção à regra de nunca
   expor erro cru — distingue banido/desativado/convite pendente).
5. **SPA sem storage de credencial**: identidade em memória, restore via
   `GET /auth/me`, 401 global volta ao login.
6. **Dependências**: `pyjwt[crypto]` removida; nenhuma nova.

## Consequências

- Banimento/revogação na plataforma refletem em ≤60s (vs. nunca, no JWT local
  de 7 dias) — ganho direto de segurança.
- XSS no oráculo não alcança mais o token da plataforma (cookie httpOnly +
  token só no servidor).
- Custo: uma chamada à plataforma por sessão a cada 60s de atividade, e o rate
  limit de 100 req/min por IP da plataforma passa a ser compartilhado pelo IP
  do BFF (mitigado pelo cache; pendência de confirmação com o time).
- Deploy exige SPA e API no **mesmo host**; split-host exigiria SameSite=None +
  CSRF token (fora da v2).
- O pedido de CORS à plataforma (`CORS_EXTRA_ORIGINS`) fica **desnecessário** —
  o browser nunca fala com ela.

## Alternativas consideradas

- **SPA guarda o token + validação remota no backend** (ajuste mínimo sobre a
  v1): descartado — token opaco de 7 dias com acesso total à conta em
  localStorage é exatamente o risco que o doc da plataforma manda evitar (§5),
  e o rework economizado não compensa.
- **Sessão própria assinada pelo FastAPI (JWT nosso) em vez de tabela**:
  descartado — sem tabela não há revogação server-side do NOSSO lado, e
  precisaríamos da tabela de qualquer forma para guardar o accessToken.
