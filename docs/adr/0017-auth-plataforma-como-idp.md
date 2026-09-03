# ADR-0017 — Plataforma Borderless como IdP; JWT validado localmente; sem Supabase

## Status

Aceito — 2026-09-03.

## Resumo

- **Decisão:** as credenciais vivem na plataforma Borderless; o FastAPI faz o bridge do login (key header de app, segredo de servidor) e a sessão do oráculo é o `accessToken` (JWT) que a plataforma emite, validado **localmente** com PyJWT. Sem Supabase. Admin de `/ops` = allowlist `ADMIN_EMAILS` (404 para os demais). Sem auth não há pergunta.
- **Aplica-se quando:** qualquer mudança em login, sessão, guards (`require_user`/`require_admin`), ownership de conversas ou proteção de rotas.
- **Regra prática:** rota nova de negócio nasce com `Depends(require_user)` (módulo expõe `router`); rota pública é exceção deliberada (`public_router` — hoje só `/auth/login` e health). Identidade se lê de `CurrentRequestContext.get_user()`, nunca de header cru.

---

## Contexto

O CLAUDE.md mantinha a autenticação como ponto em aberto; a proteção provisória era
Cloudflare Access na borda + header `Cf-Access-Authenticated-User-Email` sem validação.
O time da plataforma disponibilizou o `POST /api/auth/signin` autenticado por key
header de app, devolvendo os dados do usuário e um `accessToken` JWT com expiração
(contrato completo: `docs/autenticacao.md` §3).

O guia do socratic-dev (versão anterior de `docs/autenticacao.md`) usava Supabase como
máquina de sessão porque o contrato antigo da plataforma NÃO devolvia token. Com o
token no contrato, o Supabase perderia a única função que tinha aqui.

## Decisão

1. Bridge no FastAPI (`POST /auth/login`): rate limit durável em Postgres → signin na
   plataforma (timeout 10s, key header de `Settings`) → resposta `{user, access_token,
   expires_in, is_admin}`. Erros mapeados para códigos estáveis
   (`invalid-credentials` 401, `rate-limited` 429, `unavailable` 503).
2. Validação do JWT local (PyJWT), parametrizada por `BORDERLESS_JWT_ALGORITHM` +
   `BORDERLESS_JWT_VERIFY_KEY` (PEM pública ou segredo compartilhado — pendência §9 do
   spec muda só env). Claims esperadas: `sub`, `email`, `exp`.
3. Ownership por `user_email` do token; conversa alheia ou órfã (pré-auth) = 404.
4. Admin por allowlist `ADMIN_EMAILS`; não-admin em `/ops` = 404.
5. Cloudflare Access da borda sai quando esta auth entrar em produção.
6. Dependências novas registradas: `pyjwt` (validação) e `httpx` promovida a dep de
   produção (client do bridge).

## Consequências

- O oráculo não armazena senha nem emite token próprio; revogação/renovação são da
  plataforma (sem refresh na v1 — 401 ⇒ login de novo).
- SPA guarda a sessão em localStorage e envia Bearer; `isAdmin` no client é só UI —
  o backend recalcula da allowlist a cada request.
- Conversas antigas sem `user_email` desaparecem das listagens (deliberado).

## Alternativas consideradas

- **Supabase igual ao socratic-dev:** descartado — o token novo da plataforma cobre a
  única função que o Supabase teria; evitamos um serviço + SDK.
- **Sessão própria do FastAPI:** mais controle (revogação), mais código; desnecessário
  enquanto o TTL da plataforma atender.
