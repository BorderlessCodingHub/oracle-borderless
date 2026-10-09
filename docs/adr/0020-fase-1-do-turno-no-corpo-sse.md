# ADR-0020 — A fase 1 do turno roda no corpo SSE, em escopo de sessão próprio

## Status

Aceito — 2026-09-05. Substitui, no [ADR-0016](0016-agent-framework-langgraph.md), a seção "A restrição de sessão e o consumo em duas fases" quanto a **onde** a fase 1 roda e qual é o critério de corte. Torna obsoleta a consequência "chegam numa rajada" do [ADR-0019](0019-contrato-ag-ui-do-turno.md) e a seção 8 da spec de 2026-09-04.

## Resumo

- **Decisão:** o grafo é consumido em duas fases via `TurnGraphPort.run() -> TurnRun`: `prelude()` (gate → retrieve → recusa | entrada do `answer`) roda **no corpo SSE**, dentro de `async_session_scope()` aberto pelo controller; `stream()` roda depois, sem sessão. O corte da fase 1 é a **entrada real** do nó `answer` (evento `task` do `stream_mode="debug"`), o que também faz cada passo "acender" ao vivo. O endpoint chama duas Actions — `OpenTurnAction` no request, `RunTurnAction` no corpo — uma por escopo de sessão.
- **Aplica-se quando:** for mexer no runner, no controller de `/conversations/ask`, em qualquer coisa que precise de sessão de banco fora do request (corpo SSE, job, eval), ou quando um passo da linha do tempo não acender na hora certa.
- **Regra prática:** trabalho de banco do turno vai em `prelude()`; `stream()` nunca toca o banco. Fora do request, o escopo vem de `src/support/core/session_scope.py` — nunca `AsyncSessionLocal()` direto — e é aberto por `app`/`console`/`evals`, nunca pelo domínio (teste de fronteira). `deps` do grafo nascem em `RunTurnAction`, **dentro** do escopo em que vão rodar. Do payload `debug` só se lê `type` e `payload.name`.

---

## Contexto

O ADR-0016 resolveu a restrição de sessão (o `BaseHTTPMiddleware` fecha a sessão async antes do corpo SSE começar) rodando gate e retrieval **dentro do request**, em `await start()`, e devolvendo ao corpo só o gerador do restante. Funcionou, com um custo que o ADR-0019 registrou como consequência negativa: o navegador não recebe byte nenhum até gate + retrieval terminarem; `RUN_STARTED`, os passos `gate`/`retrieve` e o `STEP_STARTED` de `answer` chegam numa rajada com o primeiro token. A linha do tempo mostra a sequência certa, mas não acende passo a passo, e os três pontos de espera continuavam existindo — contradizendo o objetivo da spec de 04/09.

Dois fatos tornaram a mudança viável sem tocar no grafo nem no protocolo:

1. **A restrição é de escopo, não de lugar.** Os nós `retrieve` e `refuse` precisam de uma sessão viva no `ContextVar` porque os repositórios a capturam no `__init__` (regra 3). O corpo SSE já abria uma sessão própria para persistir o turno (`run_in_async_session`); o mesmo mecanismo serve para a fase 1, desde que os `deps` sejam construídos **dentro** desse escopo (lição de `tests/unit/evals/test_harness_session_scope.py`).
2. **O LangGraph avisa quando um nó começa.** `stream_mode="debug"` emite `{"type": "task", "payload": {"name": "<nó>", ...}}` na entrada de cada nó (verificado com langgraph 1.2.11: o evento chega ao consumidor antes do nó executar, e se o consumidor para de iterar ali, o nó só começa quando a iteração é retomada). Até aqui o `started` de um passo era sintetizado no `update`, que só chega no fim do nó.

## Decisão

### Três escopos de sessão por turno

```
 request (DBSessionMiddleware)   │ corpo SSE (StreamingResponse)
 ───────────────────────────────┼──────────────────────────────────────────────────────
 auth → OpenTurnAction:         │ RUN_STARTED
   find-or-create conversa      │ ┌ async_session_scope() ── escopo 2 ─────────────┐
   access policy (404)          │ │ RunTurnAction: deps + graph.run()               │
   load_recent (recência)       │ │ prelude(): gate ─► retrieve ─► (refuse | ▶answer)│
   append(pergunta)             │ │   STEP_STARTED/FINISHED ao vivo                 │
 commit ─────────────────────► │ └─────────────────────────────── fecha na entrada ┘
                                │ stream(): answer ⇄ tools, texto, fontes   (sem sessão)
                                │ ┌ run_in_async_session() ── escopo 3 ────────────┐
                                │ │ trace + resposta do assistente                 │
                                │ └────────────────────────────────────────────────┘
                                │ RUN_FINISHED  (ou RUN_ERROR antes, sem FINISHED)
```

- **Escopo 1 (request)** — tudo que precisa virar status HTTP. O commit do middleware grava conversa + pergunta antes do primeiro byte do corpo.
- **Escopo 2 (prelúdio)** — aberto no corpo pelo controller (`async_session_scope()`), dura só gate → retrieve → (refuse | entrada do `answer`). Só leitura; o commit no fim é vazio e o rollback em falha não desfaz nada. Segura uma conexão por, no máximo, o tempo que a fase 1 segurava antes — e a solta um pouco mais cedo (o corte é a entrada do `answer`, não o seu primeiro evento).
- **Escopo 3 (persistência)** — inalterado.

Entre os escopos 2 e 3 **não há sessão** no `ContextVar`: `stream()` roda answer ⇄ tools sem banco. A invariante do ADR-0016 ("dali em diante só há token de LLM e tool HTTP") continua, agora garantida por teste de integração (o fake do grafo registra `CurrentAsyncSessionContext.get()` em cada fase: sessão aberta no prelúdio, `None` no stream) e por teste do runner (o prelúdio termina com o modelo ainda bloqueado num `asyncio.Event`).

### Port

`TurnGraphPort.run(...)` é **síncrono** e devolve um `TurnRun` com `prelude()` e `stream()`. `start()` deixou de existir no port, no runner, nos fakes e no harness de eval. Chamar `stream()` antes de `prelude()` esgotar é `RuntimeError`.

### Runner

`stream_mode=["updates", "messages", "debug"]`. O `TurnEmitter.on_debug` lê **só** `type == "task"` e `payload.name`, e só para `gate`/`retrieve`/`refuse`/`answer` — o `input` do payload é o state inteiro (com o `knowledge` recuperado) e nunca sai do emitter (regra 4). O `finished` continua vindo do `update`, onde os `signals` já têm o `detail`. `step_started` é idempotente: re-entradas do `answer` no tool loop não reabrem o passo, e fakes que não emitem `debug` continuam sintetizando o `started` no update.

`buffered`, `deferred` e o ramo especial da falha do estágio de resposta saíram: como **toda** falha agora acontece no corpo, todas caem no mesmo `except` do controller.

### Actions (D4, D6)

- `OpenTurnAction` (escopo 1): conversa, policy, recência, pergunta, `TurnTraceDraft`/`TurnSignals`. Devolve `OpenedTurn`.
- `RunTurnAction` (escopo 2): monta `TurnDependencies` **no escopo em que é chamada** e devolve `graph.run(...)`. Síncrona.
- `AnswerQuestionAction` foi removida.

O endpoint chama **duas** Actions. É uma exceção deliberada à regra 5 ("uma Action"): cada Action pertence a um escopo de sessão diferente, e uma Action única não poderia montar `deps` no request (sessão errada) nem abrir escopo (regra 3 — quem abre é `app`).

### Falhas (D2)

Falha em gate/retrieve/refuse vira `RUN_ERROR` **depois dos passos já emitidos**, com trace `outcome=error` carregando o que os nós escreveram; a pergunta do usuário **permanece gravada**; a resposta não é persistida. Antes era um 500 sem stream, com rollback da pergunta e **sem trace** — impossível de manter depois que o corpo começou (headers já foram), e o trace do turno que quebrou era justamente o que o 500 perdia. Desconexão do cliente no prelúdio: `CancelledError` atravessa o `async with` do escopo 2 (rollback + close) e o turno morre sem trace, como numa desconexão durante o stream.

### Frontend (D5)

`TurnTimeline` não tem mais os três pontos. Sem atividade, a lista renderiza vazia com `aria-busy` e altura reservada de uma linha; o primeiro passo chega no round-trip HTTP. Protocolo, parser e `useAskStream` não mudam.

### Tool que precisa do banco durante `stream()` (revisão C1/mentor)

O invariante "`stream()` nunca toca o banco" descreve o que o RUNNER garante (nenhum nó do grafo entre `answer` e o fim abre sessão por conta própria); não impede uma TOOL de precisar do banco depois que o escopo 2 já fechou — `search_lesson` (modo mentor) é o primeiro caso: o modelo pode chamá-la várias vezes dentro do tool loop, todo esse loop rodando em `stream()`. A tool resolve isso abrindo o PRÓPRIO escopo curto (`async_session_scope()`, o mesmo helper do escopo 2/3) só para a duração da chamada — e a Action/Repository só podem nascer DENTRO desse `async with`, porque o Repository captura `CurrentAsyncSessionContext.get()` no `__init__`: construí-los antes (ou fora) do escopo deixaria o repositório preso à sessão já fechada do prelúdio, o que vaza conexão e falha de forma não determinística em vez de sempre. A regra prática vale para qualquer tool futura na mesma situação: se ela precisa do banco e roda em `stream()`, abre seu próprio `async_session_scope()` e constrói tudo o que capture sessão lá dentro — nunca herda a sessão de um escopo que já era do chamador.

## Consequências

**Positivas**
- A linha do tempo acende passo a passo: "Entendendo a pergunta" pulsa antes de concluir, "Buscando na base" idem, "Respondendo" aparece **antes** do primeiro token.
- Turno que quebra em gate/retrieve deixa trace e mantém a pergunta.
- Fronteiras mais explícitas: `session_scope.py` é o único lugar que abre sessão fora do request; o domínio não importa `AsyncSessionLocal` nem `session_scope` (teste).
- Deploy não precisa ser conjunto: o frontend antigo funciona contra o backend novo (só mostra os pontos por menos tempo).

**Negativas / riscos**
- Duas Actions num endpoint (exceção registrada acima).
- Dependência do formato do evento `debug` do LangGraph (`type`/`payload.name`). Se mudar, o `started` volta a ser sintetizado no `update` (degradação suave, coberta por teste), não uma quebra.
- A checagem "ao vivo" de ponta a ponta não é testável com `ASGITransport` (bufferiza o corpo inteiro); fica no teste unitário do runner (`asyncio.Event`) e na verificação manual com `curl -N`.

## Alternativas consideradas

- **Action abrir o escopo de sessão** — viola a leitura literal da regra 3 e espalha ciclo de vida de sessão pelo domínio. Rejeitada (D1).
- **Manter 500 + rollback na falha do prelúdio** — impossível com o corpo já iniciado; e perdia o trace. Rejeitada (D2).
- **Manter o corte no primeiro `messages` do `answer`** — segura a conexão Postgres durante a latência do primeiro token sem necessidade; o nó `answer` não toca o banco. Rejeitada (D3).
- **Uma Action só** — não pode montar `deps` no request nem correr o grafo; o nome passaria a mentir. Rejeitada (D4).
- **Manter os pontos como "conectando" / semear `gate` otimista no cliente** — é o que se pediu para não existir mais; desnecessário com o `started` real chegando em milissegundos. Rejeitada (D5).
- **Extrair o corpo SSE para `src/app/api/streaming/turn_stream.py`** — refactor sem ganho para o objetivo; melhoria futura. Rejeitada (D6).
- **Trocar `BaseHTTPMiddleware` por middleware ASGI puro para manter a sessão do request viva durante o corpo** — mudaria o ADR-0006 e não resolve o problema real (segurar a conexão durante o streaming). Fora de escopo.
