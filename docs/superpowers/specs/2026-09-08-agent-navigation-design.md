# Agent Navigation — design

**Data:** 2026-09-08
**Repos afetados:** `borderless-api`, `oracle-borderless`, `borderless-platform` (branch `feat/agent-navigation` em cada um)
**Status:** aprovado em brainstorm; aguardando revisão do documento

## 1. Objetivo

Substituir o vídeo explicativo de navegação por um agente que leva o membro ao lugar certo da plataforma a partir de uma frase em linguagem natural, usando os dados cadastrais dele (membership, seniority, careerStage, tags de stack, matrículas) para escolher o destino. O padrão é **tool as navigation**: o modelo chama uma tool, a fonte da verdade de acesso resolve o destino, e o browser executa o redirect.

O cérebro é o **Oracle Borderless**, produto já existente com RAG sobre a base de conhecimento do ecossistema (Notion via MCP), LangGraph com tool loop, streaming SSE de `StreamEvent`s e autenticação em ponte com a Platform. Ele passa a ser embutido na Platform como assistente.

## 2. Decisões já tomadas

| Decisão | Escolha |
| --- | --- |
| Abordagem | **A**: Oracle é o cérebro; `borderless-api` resolve destino e acesso; Next.js executa a navegação |
| Escopo da fase 1 | Barra "para onde quero ir" no header **e** painel de chat lateral |
| Base de conhecimento | Tudo que está aprovado na KB do Oracle pode ser exposto a qualquer membro autenticado da Platform |
| Redirect | Sempre no cliente. O backend nunca redireciona; devolve um destino estruturado |
| Fonte da verdade de acesso | `borderless-api`, via motor de entitlement existente (DENY vence) |
| Personalização | `membership`, `seniority`, `careerStage`, `UserTag ∩ TrailTag`, trilhas matriculadas/em progresso |

## 3. Arquitetura e fluxo de um turno

```
Platform (Next.js)                 Oracle (FastAPI + LangGraph)          borderless-api (Fastify)
──────────────────                 ────────────────────────────          ────────────────────────
Barra / Chat
  │ POST /api/oracle/conversations/ask
  │ {input:{question, mode, locale}, config:{run_id, configurable:{thread_id}}}
  ▼
Route handler (proxy)
  │ lê cookie borderless_access_token
  │ Authorization: Bearer <token>  ──────────▶ require_user (bearer)
  │                                             │ valida em GET /api/users/profile ─────▶ (cache 60s)
  │                                             ▼
  │                                           grafo: [gate] → answer ⇄ navigate
  │                                             │ navigate_platform(destination, topic, goal)
  │                                             │ POST /api/navigation/resolve (Bearer) ─▶ NavigationService
  │                                             │ ◀── {destination, access, unlock, signals, alternatives}
  │ ◀── SSE: updates{navigate:{navigation}}     │
  ▼                                             │
useNavigationAgent                              │ answer: frase final no locale
  │ valida path na allowlist                    │
  │ router.push(path) (next-intl)               ▼
  ▼                                           persiste message.navigation + trace
página de destino
```

1. A barra envia `mode: "navigate"`; o chat envia `mode: "chat"`. Ambos enviam o `locale` atual.
2. O proxy do Next.js injeta o bearer da Platform e devolve o corpo SSE em streaming. Não há CORS nem cookie cross-site.
3. O Oracle valida o bearer reaproveitando a cache de 60 s e o fail-open de 10 min já existentes. O token e um resumo do usuário entram no `configurable` do grafo, nunca em `metadata`.
4. Em `mode: navigate` o gate é pulado e `intent = navigate`. Em `mode: chat` o gate classifica `knowledge | navigate | chit_chat`. Navegação nunca passa por `retrieve` nem por `refuse`.
5. O modelo chama `navigate_platform`. A aresta pós-`answer` roteia essa chamada para o nó `navigate` (não para o `ToolNode`), que chama a API e escreve `navigation` no state.
6. O chunk `updates` do nó `navigate` sai no SSE assim que a API responde. O Next.js valida o `path` e navega antes do modelo terminar a frase.
7. O modelo escreve uma frase no idioma do `locale`: para onde levou e por quê, ou o lock e o caminho de desbloqueio. O `on_chain_end` do raiz repete `navigation`, que é persistido junto com `sources`.

## 4. borderless-api — domínio `navigation`

### 4.1 Catálogo de destinos

Fonte única, em código (`src/config/navigation-catalog.ts`). Descrições derivadas da transcrição do vídeo de navegação. Exposto em `GET /api/navigation/catalog` (autenticado) para o Oracle montar a descrição da tool e para a Platform validar paths.

| id | path | kind | descrição (o que o modelo lê) |
| --- | --- | --- | --- |
| `home` | `/` | static | Dashboard: progresso das trilhas inscritas, histórico (trilhas em progresso, code-ups feitos, próximos eventos, likes recebidos), posts do fórum e call to action. |
| `blog` | `/blog` | static | Artigos editoriais da comunidade. |
| `events` | `/events` | static | Calendário com todos os eventos: atividades da PSP, webinários, masterclasses, eventos gratuitos. Inscrição em eventos. |
| `forum` | `/forum` | static | Discussões da comunidade, posts e comentários. |
| `code_up` | `/code-up` | static | Notas de aprendizado do membro (antigo Notes). |
| `programs` | `/programs` | static | Masterclasses, webinários, acompanhamentos PSP e Base, Mock Interviews (System Design, Dados, Live Coding, Code Challenge, AI System Engineering, screening). Inclui o "Mapa do Labirinto", capítulo auxiliar do CodeBreakers dentro do acompanhamento PSP. |
| `trails` | `/trails` | static | Trilhas de aprendizado por role/membership (free, starter, base, PSP): AI, Backend, Node.js, Data Engineering, Full Stack, Python, iOS e outras. Progresso por curso. |
| `code_breakers` | `/code-breakers` | static | Desafios de algoritmos e estrutura de dados (arrays, hashing, two pointers, linked lists, trees, grafos) separados por dificuldade, com barra de progresso. |
| `leaderboard` | `/leaderboard` | static | Ranking da temporada com multiplicadores e recompensas. |
| `livestream` | `/livestream` | static | Evento ao vivo em andamento. Só disponível quando há live e o membro tem permissão. |
| `profile` | `/profile` | static | Perfil próprio: LinkedIn, GitHub, localização, tags de stack, seniority. |
| `settings` | `/settings` | static | Configurações da conta e troca de idioma (en / pt-BR). |
| `settings_purchases` | `/settings/purchases` | static | Compras, assinatura e upgrade de membership. |
| `notifications` | `/notifications` | static | Notificações do membro. |
| `trail` | `/trails/:trailId` | dynamic | Uma trilha específica, escolhida por `topic` e pelo perfil. |
| `program` | `/programs/:programSlug` | dynamic | Um programa específico (ex.: Mock Interview PSP), escolhido por `topic`. |
| `event` | `/events/:id` | dynamic | Um evento específico, escolhido por `topic` (próximo evento que casa com o tema). |

Regras do catálogo:
- Destinos `static` são sempre resolvíveis; `access` só é diferente de `allowed` onde já existe gating hoje (`livestream`).
- Destinos `dynamic` exigem resolver uma entidade; sem candidato devolve-se a listagem correspondente como destino (`trails`, `programs`, `events`) com `alternatives` vazio e `signals.fallback = true`.
- Paths saem **sem locale**. A Platform prefixa via next-intl.
- Labels: destinos `static` devolvem `labelKey` (a Platform traduz); destinos `dynamic` devolvem `label` com o nome da entidade.

### 4.2 Endpoints

`GET /api/navigation/catalog` — autenticado. Devolve `{ data: { destinations: CatalogEntry[] } }`.

`POST /api/navigation/resolve` — autenticado. Body validado por Zod:

```ts
{
  destination: string;      // id do catálogo
  topic?: string;           // tema livre: "backend node.js", "system design", "python"
  goal?: "learn" | "practice" | "network" | "interview" | "manage_account";
}
```

Resposta (fatos, sem frase pronta — o modelo escreve o texto):

```ts
{
  data: {
    destination: { id: string; path: string; labelKey?: string; label?: string };
    access: "allowed" | "locked_upgrade" | "locked_enroll" | "denied";
    unlock: null | { action: "enroll"; path: string } | { action: "upgrade"; membership: Membership; path: "/settings/purchases" };
    signals: {
      matchedTags: string[];
      inProgress: boolean;
      difficulty: "BEGINNER" | "INTERMEDIATE" | "ADVANCED" | null;
      fallback: boolean;
      profile: { membership: Membership; seniority: Seniority | null; careerStage: CareerStage };
    };
    alternatives: { id: string; path: string; labelKey?: string; label?: string }[];  // até 3
  }
}
```

Erros: `422` com `error.details.validDestinations: string[]` para id desconhecido (o modelo se corrige na chamada seguinte); `401` sem token; `404` nunca — destino dinâmico sem candidato vira fallback para a listagem.

### 4.3 Regras de resolução (nesta ordem)

1. **Static**: devolve o path do catálogo. `livestream` consulta o serviço de livestream para `access`.
2. **`trail` com `topic`**: candidatos = trilhas `PUBLISHED` cujo nome ou tags casem com o `topic` (match por slug/nome normalizado). Pontuação: `+3` trilha já em progresso do usuário, `+2` por tag em `UserTag ∩ TrailTag`, `+1` dificuldade média dos cursos compatível com `seniority` (JUNIOR→BEGINNER, MIDDLE→INTERMEDIATE, SENIOR→ADVANCED). Empate: trilha acessível ao membership atual primeiro. O vencedor passa por `TrailService.canUserAccessTrail` / `resolveTrailContainerAccess` para `access` e `unlock`. Demais candidatos viram `alternatives`.
3. **`trail` sem `topic`**: trilha em progresso mais recente; senão, melhor match de `UserTag`; senão fallback `trails`.
4. **`program` / `event` com `topic`**: match por nome/slug nas entidades publicadas e visíveis; `access` pelo entitlement de `PROGRAM` / `EVENT`. Sem candidato: fallback para a listagem.
5. **Destino omitido pelo modelo é impossível** (campo obrigatório), mas `topic` sem destino claro é decidido pelo modelo com o `careerStage` no contexto: `junior_transition` → `trail`; `mid_senior_internationalize` → `program` (mock interviews); `already_global` → `events` / `forum`; `curious` → `home`. Essa heurística vive no prompt do Oracle, não na API.
6. `access` segue a taxonomia de locks do `PRODUCT.md`. `unlock` só aparece quando a ação de fato destrava, conforme o backend já informa hoje para trilhas e programas.

### 4.4 Estrutura de código

Seguindo `Routes → Controllers → Services → Repositories`:

- `src/config/navigation-catalog.ts` — catálogo tipado.
- `src/models/navigation.model.ts` — schemas Zod de request/response.
- `src/repositories/navigation.repository.ts` — consultas: trilhas publicadas com tags e dificuldade média, tags do usuário, trilhas do usuário, programas e eventos por nome.
- `src/services/navigation.service.ts` — regras da seção 4.3; depende de `trailService`, `programService`, `eventService`, `livestreamService` já registrados.
- `src/controllers/navigation.controller.ts` + interface.
- `src/routes/api/navigation.routes.ts` registrado em `src/routes/index.ts` com `fastify.authenticate`.
- `src/container.ts` — `navigationModule` com repository, service e controller.

Sem migration: só leitura de tabelas existentes.

## 5. Oracle — assistente com navegação

### 5.1 Autenticação por bearer

- `src/app/api/dependencies/require_user.py`: lê cookie **ou** `Authorization: Bearer`. No caminho bearer chama `ResolveBearerAction` (novo, em `src/domain/users/actions/`), que faz find-or-create em `sessions` com `token_hash = hash(token)`, `platform_access_token = token`, `source = "platform_bearer"`, e depois segue o mesmo caminho de `ResolveSessionAction` (cache 60 s, fail-open ≤ 10 min, revogação apaga a sessão).
- `UserSessionModel` ganha `source: str` (`"oracle_login" | "platform_bearer"`) — migration `0010_sessions_source_and_message_navigation.py`.
- `AuthenticatedUser` ganha `platform_access_token: str` e `membership`, `community_role`, `career_stage`, `seniority` lidos do profile (o `PlatformProfile` já traz membership e community_role; adicionar `career_stage` e `seniority`).
- `settings.CORS_ORIGINS` não muda: o proxy é server-side.
- `settings.BORDERLESS_AUTH_URL` é reaproveitado como base da API (`/api/navigation/*`).

### 5.2 Contrato do `POST /conversations/ask`

`StreamInput` ganha:

```python
mode: Literal["chat", "navigate"] = "chat"
locale: Literal["en", "pt-BR"] = "pt-BR"
```

Ambos entram no `TurnState` (`mode`, `locale`). O cliente continua sem injetar `configurable`.

### 5.3 Grafo

Estado (`state.py`) ganha:

```python
mode: str                 # "chat" | "navigate"
locale: str
intent: str               # "knowledge" | "navigate" | "chit_chat"
navigation: dict | None   # resultado projetado do nó navigate
```

Gate (`nodes.py`): `_GateOutput` ganha `intent`. Prompt do gate descreve os três casos; `retrieve` só pode ser `true` com `intent == "knowledge"`. Em `mode == "navigate"` o gate não roda: `route_entry` devolve `"answer"` com `intent = "navigate"`, `retrieve = False`.

Arestas (`edges.py`):
- `route_entry`: `preset_knowledge` → `answer`; `mode == "navigate"` → `answer`; senão `gate`.
- `should_retrieve`: `retrieve and intent == "knowledge"` → `retrieve`; senão `answer`.
- `has_grounding`: inalterada.
- `after_answer` (nova, substitui `tools_condition`): sem tool call → `END`; tool call `navigate_platform` → `navigate`; outras → `tools`.
- `navigate` → `answer`; `tools` → `answer`.

Nó `navigate` (`src/support/agent/graph/navigate_node.py`):
- Lê a `AIMessage` final com o tool call, extrai `destination`, `topic`, `goal`.
- Se `state["navigation"]` já existe → devolve `ToolMessage(status="error")` com "uma navegação por turno".
- Chama `BorderlessNavigationClient.resolve(...)` (`src/support/clients/borderless/borderless_navigation_client.py`, httpx, timeout 8 s) com o bearer de `configurable["platform_token"]`.
- Sucesso: `ToolMessage` com o JSON embrulhado em `<<TOOL_CONTENT>>`; state `navigation = {destination, access, unlock, signals: {matchedTags, inProgress, difficulty, fallback}, alternatives}` (sem o `profile` — o modelo já o tem no prompt).
- `422`: `ToolMessage(status="error")` com os ids válidos; sem `navigation`.
- Timeout/5xx: `ToolMessage(status="error")` "plataforma indisponível"; sem `navigation`.
- Incrementa `signals.tool_calls`, seta `signals.navigation_called`, `signals.navigation_access`.

Roda na fase `stream()` sem sessão de banco (é HTTP), como `web_search`.

### 5.4 Tool e prompt

`build_tools()` passa a devolver `[web_search, fetch_notion_page, navigate_platform]`. `navigate_platform` é declarada só para o modelo (schema + docstring); a execução é o nó `navigate`. Args: `destination: str`, `topic: str | None`, `goal: Literal[...] | None`.

Docstring montada por `NavigationCatalog.describe()`:
- Busca `GET /api/navigation/catalog` na primeira chamada; cache em memória por 1 h (`settings.NAVIGATION_CATALOG_TTL_S`).
- Fallback: snapshot embutido em `src/support/agent/navigation_catalog_snapshot.json`, com teste que compara o snapshot ao catálogo da API quando `BORDERLESS_AUTH_URL` estiver acessível no CI de integração.

`SYSTEM_PROMPT` ganha o bloco **NAVEGAÇÃO**:
- Quando o usuário quer ir a um lugar, encontrar algo ou começar uma atividade na plataforma, chame `navigate_platform` com o `destination` do catálogo. Use `topic` quando houver tema. Use o perfil fornecido (membership, seniority, careerStage) e a heurística da seção 4.3.5 para escolher entre `trail`, `program`, `events`, `home`.
- Depois do resultado: uma frase, no idioma indicado em `locale`, dizendo para onde levou e por quê, usando `signals`. Se `access != allowed`, explique o lock e ofereça o `unlock` devolvido; nunca prometa algo que a tool não devolveu.
- Intenção ambígua: uma pergunta de esclarecimento, sem chamar a tool.
- Em `mode: navigate` sem destino identificável: responda em uma frase e sugira abrir o chat; não recuse com a RESPOSTA PADRÃO.
- Nunca invente destinos, paths ou nomes de trilha.

O perfil do usuário entra em `_answer_messages` como bloco `Perfil do usuário:` (membership, seniority, careerStage, locale). A regra 1 do prompt ("responda somente com base no `<<TOOL_CONTENT>>`") passa a excluir explicitamente navegação e conversa, que não exigem contexto recuperado.

### 5.5 Redator, persistência e trace

- `runner.py`: `_STATE_KEYS` ganha `"intent"`; `_project` copia `navigation` com allowlist de chaves (`destination`, `access`, `unlock`, `signals`, `alternatives`). Nó `navigate` entra em `_STEP_NODES` para emitir `on_chain_start/end` como passo.
- `ports.py`: `navigation_of(event)` análogo a `citations_of`, lendo o `updates` do nó `navigate` e o `on_chain_end` do raiz.
- `MessageModel` ganha `navigation: JSONB | None`; `AppendAssistantMessageAction` grava; `GET /conversations/{id}` devolve `navigation` por mensagem.
- `TurnSignals` ganha `intent`, `navigation_called: bool`, `navigation_access: str | None`; `agent_traces` ganha as colunas correspondentes (mesma migration 0010).
- Evals: `evals/cases/navigation_set.json` com casos de barra e de chat; o juiz verifica `destination.id` esperado, ausência da frase de recusa e idioma da resposta.

### 5.6 Frontend do Oracle

Sem mudanças obrigatórias. Opcional: renderizar o card de `navigation` no chat do próprio Oracle, reaproveitando o mesmo `AskEvent`.

## 6. Platform (Next.js)

### 6.1 Configuração

- `ORACLE_API_URL` (server-only) e `NEXT_PUBLIC_ORACLE_ENABLED` em `.env.example` e `src/lib/constants.ts`.
- Sem flag ativa, header não renderiza barra nem ícone do chat.

### 6.2 Proxy

`src/app/api/oracle/[...path]/route.ts`:
- Métodos `GET` e `POST`. Lê `borderless_access_token` do cookie; sem token → `401`.
- Encaminha para `${ORACLE_API_URL}/${path}` com `Authorization: Bearer`, `Content-Type` e `Accept` originais. Devolve `response.body` como stream, preservando `Content-Type: text/event-stream`.
- Timeout de 20 s para o primeiro byte; depois, streaming sem limite até o Oracle fechar.
- Allowlist de paths: `conversations`, `conversations/ask`, `conversations/:id`. Qualquer outro → `404`.

### 6.3 Cliente e eventos

`src/services/api/oracle/`:
- `sse.ts` e `stream-events.ts`: portagem do `frontend/src/lib/api/` do Oracle, adaptada ao `apiRoutes` local.
- `types.ts`: `AskEvent` com o evento novo `{ type: "navigation"; navigation: NavigationResult }`, emitido do chunk `updates` do nó `navigate` e do `on_chain_end` do raiz (deduplicado por turno).
- `conversations.ts`: `askStream({ question, mode, locale, conversationId })`, `listConversations`, `getConversation`.

### 6.4 Hooks

- `src/hooks/oracle/use-oracle-turn.ts`: estado do turno (tokens, passos, fontes, navegação, erro), cancelamento via `AbortController`.
- `src/hooks/oracle/use-navigation-agent.ts`: recebe `NavigationResult`, valida `path` com `isAllowedNavigationPath` (`src/lib/navigation-allowlist.ts`: rotas estáticas de `appRoutes` + padrões `/trails/[^/]+`, `/programs/[^/]+`, `/events/[^/]+`, `/user/[^/]+`), e chama `useRouter().push(path)` de `src/i18n/navigation.ts`. Se `access !== "allowed"`, navega mesmo assim (conteúdo bloqueado é visível por produto). Path inválido: não navega; devolve `{ blocked: true }` para a UI mostrar o destino como texto.

### 6.5 UI

- `src/components/header/navigation-bar.tsx`: `Command` do cmdk. Placeholder traduzido ("Para onde você quer ir?" / "Where do you want to go?"). `Enter` envia com `mode: "navigate"` e `locale` atual. Abaixo do input: frase em streaming e estado (`Levando você para…`, erro, esclarecimento). Fecha e limpa ao navegar. Atalho `Ctrl/Cmd+K`.
- `src/components/oracle/oracle-chat-panel.tsx`: `Sheet` lateral aberto por ícone no header. Lista de mensagens com Markdown (`ui/markdown.tsx`), passos (`gate`, `retrieve`, `navigate`) discretos, bloco de fontes, card de navegação com o destino e botão "Ir de novo". Histórico via `listConversations`; nova conversa por botão. Envia `mode: "chat"`.
- Copy em `src/messages/en/oracle.json` e `src/messages/pt-BR/oracle.json`; `pnpm i18n:check` passa.
- Acessibilidade: barra e painel operáveis por teclado; foco vai ao input ao abrir e ao `h1` da página após navegar; `aria-live="polite"` na frase em streaming; reduced-motion respeitado nas transições do Sheet.

## 7. Casos de borda

| Caso | Comportamento |
| --- | --- |
| Não autenticado | Barra e ícone não renderizam; proxy devolve 401 sem chamar o Oracle |
| Oracle indisponível / lento | Barra mostra "Não consegui te levar agora, use o menu ao lado"; header não bloqueia; timeout 20 s |
| Intenção ambígua ("quero melhorar") | Modelo faz uma pergunta de esclarecimento; sem tool; input mantido |
| Pergunta de conhecimento na barra | Sem RAG no modo `navigate`; resposta em uma frase sugerindo o chat; nunca a RESPOSTA PADRÃO |
| Destino bloqueado | Navega para a página; agente explica o lock com o `unlock` devolvido; sem `unlock`, só explica |
| Path inválido vindo do modelo | API rejeita id desconhecido (422); frontend revalida na allowlist; falhou, não navega e mostra texto |
| Duas navegações no turno | Nó `navigate` devolve erro na segunda; `navigation` do state não muda |
| Token da Platform expirado | Oracle 401 → proxy repassa → cliente dispara o tratamento do `api-client` (limpa cookie, redireciona) |
| Membership mudou há < 60 s | Cache do Oracle só afeta autenticação; `access` vem da API na hora, nunca defasado |
| Locale | Vai no `input`; prompt exige resposta nesse idioma sem inferir pelo texto |
| Injeção via nome de trilha/tag | Resultado da API entra em `<<TOOL_CONTENT>>`; regra 3 do prompt já cobre |
| Rate limit | `rate_limits` do Oracle continua por usuário; a barra mostra a mensagem de limite |
| Catálogo da API fora no boot do Oracle | Snapshot embutido; log de aviso; nova tentativa após o TTL |

## 8. Testes

**borderless-api** (`test/unit/services/navigation.service.test.ts`, `test/unit/routes/navigation.routes.test.ts`): static allowed; `livestream` gated; `trail` por tag com interseção; trilha em progresso vence tag; seniority desempata; DENY vence ALLOW e membership; `locked_upgrade` com `unlock.membership`; `locked_enroll` com `unlock.path`; `topic` sem candidato → fallback `trails`; id desconhecido → 422 com `validDestinations`; sem token → 401.

**Oracle** (`tests/unit/...`): gate com `intent` nos três casos; `mode: navigate` pula gate; `should_retrieve` ignora `retrieve=true` quando `intent != knowledge`; `after_answer` roteia para `navigate` / `tools` / `END`; nó `navigate` com `httpx.MockTransport` (sucesso, 422, timeout, segunda chamada); redator projeta `navigation` só com chaves permitidas e emite `navigate` como passo; `require_user` bearer (find-or-create, cache, revogação); `StreamInput` com `mode`/`locale` padrão e inválido; migration 0010 sobe e desce; `navigation_of`. Evals: `navigation_set.json` rodando no harness existente.

**Platform**: sem runner unitário no repo; cobertura via Playwright em `e2e/tests/oracle/` com um servidor SSE fake em `e2e/fixtures/oracle-fake-server.ts`: navegação bem-sucedida navega e mostra a frase; lock mostra explicação e navega; path inválido não navega; Oracle fora mostra fallback; painel abre, envia, recebe fontes; `pnpm i18n:check` no CI.

## 9. Ordem de entrega

1. **borderless-api**: catálogo, resolver, endpoints, testes. Entregável isolado e testável com `curl`.
2. **Oracle**: bearer auth + migration; `mode`/`locale`; gate com `intent`; nó `navigate` + client; redator; persistência; prompt; evals.
3. **Platform**: proxy; cliente SSE; hooks; barra.
4. **Platform**: painel de chat; i18n; a11y; E2E.
5. **Conteúdo**: página "Mapa da plataforma" no Notion aprovada na KB do Oracle, a partir da transcrição do vídeo.

Cada repo terá seu próprio plano de implementação derivado deste spec.

## 10. Fora de escopo

- Onboarding pós-cadastro conduzido pelo agente (fase futura; reaproveita a mesma tool).
- Ações além de navegar (matricular, inscrever em evento, alterar idioma). A tool só resolve destino.
- Recomendação de trilha sem interação (dashboard V1 do free cobre isso).
- Mudanças no frontend do Oracle além do opcional da seção 5.6.
- Exposição do chat a usuários não autenticados.
