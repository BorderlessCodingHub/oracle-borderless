# ADR-0022 — Tool de navegação: nó dedicado, sessões por bearer e catálogo por turno

## Status

Aceito — 2026-09-08. Estende o ADR-0021 (contrato `StreamEvent`) e o ADR-0018
(auth BFF) com um segundo caminho de identidade e um nó novo no grafo.

## Resumo

- **Decisão:** `navigate_platform` é declarada para o modelo mas executada por
  um nó próprio do grafo (`navigate`), não pelo `ToolNode`, para que o destino
  resolvido entre no state e saia no fio antes da frase final; a Platform
  autentica esse caminho com `Authorization: Bearer`, resolvido em sessões
  (`sessions`, `source="platform_bearer"`) que reaproveitam o cache/fail-open
  já existentes; o catálogo de destinos é buscado por turno com o token do
  usuário (cache de 1h por processo) e cai para um snapshot embutido quando
  falta token ou a API está fora.
- **Aplica-se quando:** for mexer na tool de navegação, no nó `navigate`, no
  caminho de auth por bearer, no catálogo de destinos, ou for entender por que
  a barra da Platform recebe o destino antes do modelo terminar de escrever.
- **Regra prática:** `navigate_platform` continua declarada em `build_tools()`
  (schema + docstring), mas seu corpo levanta `RuntimeError` de propósito —
  quem responde é `navigate_node`, chamado pela aresta `after_answer` quando a
  última `AIMessage` tem uma tool call `navigate_platform`. Uma navegação por
  turno: uma segunda chamada no mesmo turno devolve `ToolMessage(status="error")`
  e o `state["navigation"]` já resolvido não muda. O token só existe em
  `configurable["platform_token"]`, nunca em `metadata` nem em log. O
  `EventRedactor` projeta `navigation` por allowlist (`destination`, `access`,
  `unlock`, `signals`, `alternatives` — sem `signals.profile`) no chunk
  `updates` do nó `navigate` (que entra em `_STEP_NODES` e abre/fecha uma vez
  por run) e repete a mesma projeção no `on_chain_end` do raiz. `mode`/`locale`
  chegam por `input` (`StreamInput.mode`, `StreamInput.locale`), do mesmo jeito
  que `question` — nunca por `configurable` (ADR-0021). `require_user` lê
  `Authorization: Bearer` antes do cookie; bearer desconhecido cria sessão via
  `ResolveBearerAction`, bearer conhecido segue direto para
  `ResolveSessionAction` (cache 60 s / fail-open ≤ 10 min).

---

## Contexto

O design de "agent navigation" (`docs/superpowers/specs/2026-09-08-agent-navigation-design.md`,
§3, §5, §7) decidiu que o Oracle Borderless é o **cérebro** da navegação: o
modelo interpreta a intenção em linguagem natural e chama uma tool; a
`borderless-api` é a fonte da verdade de acesso e resolve o destino concreto a
partir do perfil do membro; o Next.js só executa o redirect no cliente. O
Oracle já tinha RAG sobre a base do Notion, streaming de `StreamEvent`s
(ADR-0021) e autenticação em ponte com a Platform (ADR-0017/0018) — a tarefa
era embutir esse terceiro modo (navegação) sem abrir um segundo vocabulário de
evento nem uma segunda identidade paralela.

Dois problemas concretos vinham do jeito "óbvio" de fazer isso:

1. **Tool comum (`ToolNode`) não expõe o destino a tempo.** Se
   `navigate_platform` fosse só mais uma tool no `ToolNode` prebuilt, o
   resultado ficaria preso dentro do `ToolMessage` até o modelo terminar de
   escrever a frase final — a barra da Platform só saberia para onde navegar
   depois do último token, quando a spec pede que o `router.push` aconteça
   **antes** disso (§3, passo 6).
2. **A barra usa o mesmo bearer da Platform, não o cookie do Oracle.** O proxy
   do Next.js (`src/app/api/oracle/[...path]/route.ts`, fora deste repo) injeta
   `Authorization: Bearer <token da Platform>` — não há cookie `ob_session`
   nesse caminho. Era preciso uma segunda forma de chegar a `AuthenticatedUser`
   sem duplicar o cache de 60 s / fail-open de 10 min que `ResolveSessionAction`
   já implementa (ADR-0018).

## Decisão

**1. `navigate` é um nó do grafo, não uma execução do `ToolNode`.**
`build_tools()` (`src/support/agent/tools.py`) declara `navigate_platform` só
para o modelo ver (schema + docstring); o corpo da função levanta
`RuntimeError` de propósito — chegar lá é erro de programação, porque
`tool_node_tools()` filtra `navigate_platform` para fora da lista que o
`ToolNode` executa. A aresta `after_answer` (`src/support/agent/graph/edges.py`,
substitui o `tools_condition` prebuilt) olha a última `AIMessage`: sem tool
call vai a `END`; uma chamada a `navigate_platform` vai ao nó `navigate`
(`src/support/agent/graph/navigate_node.py`); qualquer outra vai a `tools`.
`navigate_node` chama `BorderlessNavigationClient.resolve(...)` com o bearer de
`configurable["platform_token"]`, HTTP puro (roda em `stream()`, sem sessão de
banco — mesma fase que `web_search`, ADR-0020), e escreve `navigation =
result.to_public()` no state. `after_answer` e `navigate → answer` fecham o
laço: o modelo recebe o `ToolMessage` (`result.to_tool_text()`, que inclui
`signals.profile` para frasear a resposta) e escreve a frase final no
`locale` pedido. Uma navegação por turno: se `state["navigation"]` já existe,
a chamada seguinte devolve `ToolMessage(status="error")` sem sobrescrever o
destino resolvido.

**2. Sessões por bearer reaproveitam `sessions` e o cache/fail-open existente.**
`require_user` (`src/app/api/dependencies/require_user.py`) lê
`Authorization: Bearer <token>` (exatamente dois campos, `Bearer` case-
insensitive) antes de olhar o cookie; qualquer outra forma de header cai no
caminho do cookie de sempre. Bearer presente chama
`ResolveBearerAction.execute` (`src/domain/users/actions/resolve_bearer_action.py`):
busca a sessão por `token_hash`; se já existe, delega para
`ResolveSessionAction` (mesmo cache de 60 s / fail-open ≤ 10 min do ADR-0018);
se não existe, valida o bearer UMA vez em `GET /api/users/profile` e cria a
sessão com `source="platform_bearer"`, `platform_access_token=<token>` e o
snapshot de perfil (`user_membership`, `user_seniority`, `user_career_stage`).
A coluna `source` (`"oracle_login" | "platform_bearer"`) e as três colunas de
perfil chegam pela migration `0010_sessions_bearer_profile.py`.
`AuthenticatedUser` ganha `platform_access_token` (só server-side, nunca em
evento/log) e `membership`/`seniority`/`career_stage`, lidos do mesmo
snapshot.

**3. `mode`/`locale` entram por `input`, como `question` (ADR-0021).**
`StreamInput` (`src/app/api/requests/stream_events_request.py`) ganha
`mode: Literal["chat", "navigate"] = "chat"` e
`locale: Literal["en", "pt-BR"] = "pt-BR"`. `TurnState` carrega os dois mais
`intent` (`"knowledge" | "navigate" | "chit_chat"`, escrito pelo gate) e
`navigation: dict | None`. Em `mode == "navigate"`, `route_entry`
(`src/support/agent/graph/edges.py`) pula o `gate` inteiro e vai direto a
`answer`; `TurnGraphRunner.run` (`src/support/agent/graph/runner.py`) preseta
`signals.intent = "navigate"` nesse caso, porque o gate — que normalmente
escreve `signals.intent` — não roda. Em `mode == "chat"`, o `gate` classifica
os três casos (`_GateOutput.intent`) e `should_retrieve` só manda para
`retrieve` quando `retrieve and intent == "knowledge"` — navegação e
conversa fiada nunca tocam o RAG, mesmo que o campo `retrieve` solto viesse
`True`.

**4. Catálogo por turno com o token do usuário, snapshot como fallback.**
`NavigationCatalog.describe(access_token)` (`src/support/agent/navigation_catalog.py`)
busca `GET /api/navigation/catalog` com o bearer do turno corrente e cacheia o
resultado por **processo** por `NAVIGATION_CATALOG_TTL_S` (default 3600 s,
`src/support/core/settings.py`); sem token ou com a chamada falhando, cai para
o snapshot embutido (`src/support/agent/navigation_catalog_snapshot.json`),
formatado pelo mesmo `_format_entries` que o catálogo ao vivo usa — a API
segue sendo a fonte da verdade, um id fora dela ainda volta como `400
VALIDATION` com `validDestinations`. Isso **desvia da spec §5.4** ("cache em
memória por 1h", implicitamente aquecível no boot): o endpoint exige token de
usuário autenticado, e o Oracle não tem um token de serviço/backend para
aquecer esse cache antes do primeiro turno. `_build_extra_config` (no
controller, ver decisão 5) busca o catálogo no escopo do request — HTTP puro,
não captura sessão de banco — e injeta o texto pronto em
`configurable["navigation_catalog_text"]`; `_answer_model` usa esse texto para
montar a tool (`build_tools(navigation_catalog_text)`), e sem ele
`build_tools()` cai no mesmo `NavigationCatalog.snapshot_text()`.

**5. Persistência: `navigation` na mensagem, sinais no trace.**
`messages.navigation` (JSONB) e `agent_traces.intent` / `.navigation_called` /
`.navigation_access` chegam pela migration `0011_navigation_persistence.py`.
`ConversationController.ask` (`src/app/api/controllers/conversation_controller.py`)
monta `extra_config` no escopo do request (`_build_extra_config`): token,
perfil (`membership`, `seniority`, `careerStage`) e o texto do catálogo, que
viram `configurable` do grafo via `RunTurnAction.execute(turn,
extra_config=extra_config)`. `capture()` lê `navigation_of(event)`
(`src/support/agent/ports.py`) a cada evento do fio e guarda o último valor
não nulo; `_persist_turn` grava via
`AppendAssistantMessageAction(...).execute(conversation_id, content, citations,
navigation=navigation)`. `MessageResponse.navigation`
(`src/app/api/responses/conversation_responses.py`) devolve o campo em
`GET /conversations/{id}`.

**6. Regra 4 (nada confidencial, nada que não devia cruzar o port) cobre
navegação em duas camadas.** `NavigationResult.to_public()`
(`src/support/clients/borderless/borderless_navigation_client.py`) já corta
`signals.profile` antes de o resultado entrar no state — é o que o modelo NÃO
vê de volta no fio, só na resposta HTTP que ele mesmo recebeu como
`ToolMessage` (via `to_tool_text()`, que inclui o profile para o modelo
frasear). O `EventRedactor` (`src/support/agent/graph/runner.py`,
`_project_navigation`) não confia nesse formato e reaplica uma allowlist
própria (`_NAV_TARGET_KEYS`, `_NAV_SIGNAL_KEYS`, `_NAV_UNLOCK_KEYS`) — segunda
barreira, testável sem depender do client HTTP. `navigate` entra em
`_STEP_NODES`: emite `on_chain_start`/`on_chain_end` como passo (abre e fecha
uma vez por run, mesmo que o modelo insista após um destino inválido), e é o
`on_chain_end` desse nó — refletido no chunk `["updates", {"navigate":
{"navigation": ...}}]` do raiz — que carrega o destino ao cliente antes da
frase final; o mesmo `navigation` (já projetado) é repetido no
`on_chain_end` do raiz (`output.navigation`), para o cliente que só olha o
evento final.

## Consequências

**Positivas**

- O destino chega ao cliente (e a barra pode navegar) antes de o modelo
  terminar de escrever a frase — a exigência central da spec (§3, passo 6) só
  é atingível com um nó dedicado escrevendo no state; um `ToolNode` comum
  prenderia o resultado dentro do `ToolMessage` até o fim do turno.
- Reaproveitar `sessions`/`ResolveSessionAction` para o bearer evita duplicar
  cache de 60 s, fail-open de 10 min e revogação — o segundo caminho de
  identidade herda as mesmas garantias testadas do primeiro, com o diferencial
  isolado numa única coluna (`source`).
- O snapshot embutido mantém a tool sempre descritível (nunca sem catálogo),
  mesmo com a API de navegação fora ou o turno sem token; a API continua
  sendo a única fonte que valida ids de verdade.
- Duas barreiras independentes (`to_public()` no client + allowlist no
  redator) protegem a regra 4 mesmo se uma das duas tiver um bug.

**Negativas / riscos**

- Buscar o catálogo com o token do usuário, por turno, adiciona uma chamada
  HTTP extra na primeira vez que cada processo atende um turno de navegação
  (mitigado pelo cache de 1h por processo — `NavigationCatalog._cache` é de
  classe, compartilhado entre turnos do mesmo worker). Processos que reiniciam
  com frequência (ex.: deploy) pagam esse custo mais vezes que o "cache no
  boot" original da spec previa.
- **Pendência operacional, fora do código:** a spec (§5.4, último bullet;
  §9, item 5) prevê criar a página "Mapa da plataforma" no Notion, aprovada
  na KB, a partir da transcrição do vídeo de navegação, para o Oracle poder
  explicar áreas com citações. Essa página **não foi criada** como parte desta
  tarefa de documentação nem das Tasks 1–10 — é um passo de conteúdo, manual,
  que continua pendente antes de a navegação por chat "explicar" o destino com
  fonte citável (a navegação em si já funciona sem essa página; o que falta é
  a citação).
- Sessões por bearer e por cookie dividem a mesma tabela e o mesmo model
  (`UserSessionModel`/`sessions`); um bug em `ResolveSessionAction` afeta os
  dois caminhos de identidade. A coluna `source` isola o cenário nos testes,
  mas não existe partição física entre os dois usos.
- Uma navegação por turno é uma trava no nível do nó (checagem de
  `state["navigation"]`), não no protocolo: se o modelo insistir numa segunda
  chamada, o turno gasta uma rodada extra de tool call só para receber o erro
  "uma navegação por turno" antes de escrever a frase final.

## Alternativas consideradas

- **`ToolNode` executando `navigate_platform` e o controller "parseando" o
  `ToolMessage` depois.** Rejeitada: o destino só ficaria visível depois do
  modelo terminar a resposta inteira (o `ToolNode` roda dentro do tool loop,
  antes de qualquer token da frase final ser emitido do jeito que a spec
  pede), e exigiria extrair JSON do conteúdo de uma mensagem de texto em vez
  de ler um campo tipado do state.
- **Buscar o catálogo no boot, com um token de serviço/backend.** Rejeitada:
  `GET /api/navigation/catalog` exige autenticação de usuário; não existe hoje
  um token de serviço ou escopo de backend na `borderless-api` para essa
  chamada, e criar um exigiria uma decisão própria fora do escopo desta
  entrega. O catálogo por turno com fallback de snapshot resolve o mesmo
  problema (tool sempre descritível) sem essa dependência nova.
- **Tabela própria para sessões de bearer**, separada de `sessions`.
  Rejeitada: duplicaria cache de 60 s, fail-open de 10 min e lógica de
  revogação já implementados e testados em `ResolveSessionAction`; a coluna
  `source` basta para diferenciar a origem sem duplicar comportamento.
