# Fase 1 do turno ao vivo no corpo SSE — design

**Data:** 2026-09-05
**Status:** para revisão — decisões D1–D6 abertas até o Duanne aprovar; depois vira plano via writing-plans
**Evolui:** [spec AG-UI de 2026-09-04](2026-09-04-ag-ui-turno-design.md), seções 7 e 8
**ADR resultante:** ADR-0020 (substitui a seção "consumo em duas fases" do ADR-0016 quanto a *onde* a fase 1 roda)

> **Nota (2026-09-07):** o corte da fase 1 deixou de usar o `task` do
> `stream_mode="debug"`; é o `on_chain_start` do nó `answer` no
> `astream_events` (ADR-0021). O restante desta spec continua válido.

## Contexto

A spec de 04/09 entregou o contrato AG-UI e a linha do tempo do turno, mas
registrou na seção 8 uma limitação aceita: por causa do consumo em duas fases
do ADR-0016, o corpo SSE só começa **depois** que gate e retrieval terminaram
dentro da sessão de banco do request. Até lá o navegador não recebe byte
nenhum; `RUN_STARTED`, `STEP_*` de `gate` e `retrieve` e `STEP_STARTED` de
`answer` chegam numa rajada com o primeiro token.

Na prática (observado em 04/09 com o app rodando): a bolha do assistente abre
com os três pontos de espera, fica assim durante gate + retrieval + latência
até o primeiro token, e só então a linha do tempo aparece — já com dois passos
concluídos e o texto correndo. A linha do tempo mostra a sequência certa, mas
não "acende" passo a passo, e os três pontos continuam existindo, o que
contradiz o objetivo da spec anterior.

Esta spec faz a fase 1 acontecer ao vivo. Dois fatos tornam isso viável sem
mexer no grafo nem no protocolo:

1. **A restrição de sessão é de *escopo*, não de *lugar*.** O `retrieve` e o
   `refuse` precisam de uma sessão async viva no `ContextVar`
   (`CurrentAsyncSessionContext`), porque os repositórios a capturam no
   `__init__` (regra 3). O ADR-0016 resolveu isso rodando a fase 1 dentro do
   request. Mas o corpo SSE já abre uma sessão própria para persistir o turno
   (`run_in_async_session`, no controller) — o mesmo mecanismo serve para a
   fase 1, desde que os `deps` sejam construídos **dentro** desse escopo
   (lição já registrada em `tests/unit/evals/test_harness_session_scope.py`).
2. **O LangGraph avisa quando um nó *começa*.** `stream_mode="debug"` emite um
   evento `{"type": "task", "payload": {"name": "<nó>", ...}}` na entrada de
   cada nó (verificado com langgraph 1.2.11). Hoje o `started` de um passo é
   sintetizado no `update`, que só chega no **fim** do nó — mesmo com a fase 1
   ao vivo, "Entendendo a pergunta" apareceria já concluído. Com o `task`, o
   passo acende quando de fato começa.

### O que NÃO muda

- O grafo (`builder.py`, `nodes.py`, `edges.py`) — nenhum nó, aresta ou prompt.
- O protocolo no fio: mesmos eventos, mesma ordem, mesmo encoder
  (`ag_ui_encoder.py`), mesmo parser no frontend (`agui.ts`, `useAskStream`).
  Muda **quando** cada evento chega, não **o que** chega.
- Onde a pergunta do usuário e a conversa são gravadas: no request, antes do
  corpo SSE. 401/404/422 continuam sendo status HTTP.
- Persistência pós-stream (`_persist_turn`), `TurnTraceDraft`, `TurnSignals`,
  medição de `first_token_ms`/`engine_ms` no grafo.
- Regra 4: nada de conteúdo de tool, `page_id`, e-mail ou estado do grafo no
  fio. O payload `debug` carrega o `input` do nó (o state inteiro, com o
  `knowledge` recuperado) — o emitter lê **só** `type` e `payload.name`.

## Decisões para revisão

Tomadas aqui para não bloquear o plano; cada uma pode ser revertida antes de
executar.

| # | Decisão | Alternativa descartada |
|---|---|---|
| D1 | A fase 1 roda no corpo SSE dentro de um escopo de sessão próprio, aberto pela camada `app` (controller), como já acontece com `_persist_turn`. | Action abrir o escopo: viola a leitura literal da regra 3 e espalha ciclo de vida de sessão pelo domínio. |
| D2 | Falha em gate/retrieve/refuse vira `RUN_ERROR` com trace `outcome=error`, e a pergunta do usuário **permanece gravada**. | Manter 500 + rollback da pergunta: impossível depois que o corpo começou (headers já foram), e o trace do turno que quebrou era justamente o que o 500 perdia. |
| D3 | O corte da fase 1 passa a ser a **entrada real** do nó `answer` (evento `task` do modo `debug`), não mais o primeiro evento `messages` dele. | Manter o primeiro `messages`: segura a conexão Postgres durante a latência do primeiro token sem necessidade — o nó `answer` não toca o banco. |
| D4 | `AnswerQuestionAction` é renomeada para `OpenTurnAction` (grava a pergunta, carrega recência) e nasce `RunTurnAction` (monta `deps` dentro do escopo, dispara o grafo). | Manter uma Action só: ela não pode montar `deps` no request (sessão errada) nem correr o grafo; o nome passaria a mentir. |
| D5 | Os três pontos saem do `TurnTimeline`. Sem atividade, a lista renderiza vazia com altura reservada de uma linha; o primeiro passo chega no round-trip HTTP. | Manter os pontos como "conectando": é o que o usuário pediu para não existir mais. Semear `gate` otimista no cliente: desnecessário com o `started` real chegando em milissegundos. |
| D6 | O endpoint chama duas Actions (uma por escopo de sessão). Exceção registrada no ADR-0020 à regra 5 ("uma Action"). | Extrair o corpo SSE para `src/app/api/streaming/turn_stream.py`: refactor sem ganho para o objetivo; fica como melhoria futura. |

## Fora de escopo

- Persistir a linha do tempo (segue só ao vivo, ADR-0019).
- Mover a gravação da pergunta/conversa para dentro do corpo SSE.
- Qualquer evento novo, `STATE_*`, ou mudança em `RunAgentInput`.
- Mudar `retry` do frontend, `demoStream`, ou a página de ops.
- Trocar `BaseHTTPMiddleware` por middleware ASGI puro para manter a sessão
  do request viva durante o corpo (mudaria o ADR-0006 e não resolve o
  problema real: segurar a conexão durante o streaming).

## 1. Os três escopos de sessão do turno

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

- **Escopo 1 (request)** — inalterado, exceto que não roda mais o grafo. Tudo
  que precisa virar status HTTP acontece aqui. O commit do middleware grava
  conversa + pergunta antes do primeiro byte do corpo.
- **Escopo 2 (prelúdio)** — novo. Aberto no corpo, dura só gate → retrieve →
  (refuse | entrada do answer). Só leitura no banco (pgvector, `documents`,
  `nearest_distance`); o `commit` no fim é vazio e o `rollback` em falha não
  desfaz nada. Segura uma conexão por, no máximo, o tempo que a fase 1 segurava
  hoje (D3 a solta um pouco antes) — muda o *checkout*, não a concorrência.
- **Escopo 3 (persistência)** — inalterado (`_persist_turn`).

Entre os escopos 2 e 3 **não há sessão** no `ContextVar`: `stream()` roda
answer ⇄ tools sem banco, como hoje. É a mesma invariante do ADR-0016
("dali em diante só há token de LLM e tool HTTP"), agora garantida por teste
(seção 9), não só por comentário em `tools.py`.

**ContextVars e tarefas.** O corpo do `StreamingResponse` roda numa task
própria, com uma **cópia** do contexto; o `finally` do `DBSessionMiddleware`
limpa o `ContextVar` na task do middleware, não na do corpo — por isso hoje o
corpo herda a referência à sessão já fechada, e por isso `_persist_turn`
precisa setar a sua. O escopo 2 faz o mesmo: `set` na entrada, `clear` no
`finally`. Nós do grafo rodam em sub-tasks criadas pelo LangGraph a cada
passo e herdam o contexto **do momento em que são criadas**: `gate`/`retrieve`
/`refuse` nascem dentro do escopo 2 e veem a sessão; `answer`/`tools`
nascem depois e veem `None` — exatamente o desejado.

**Desconexão do cliente.** O Starlette cancela a task do corpo;
`CancelledError` sobe pelo `yield` do gerador, atravessa o `async with` do
escopo 2 (rollback + close no `__aexit__`) e o turno morre sem trace — igual
ao comportamento de hoje numa desconexão durante o stream.

## 2. `src/support/core/session_scope.py`

Ganha um context manager ao lado da função existente:

```python
@asynccontextmanager
async def async_session_scope() -> AsyncIterator[AsyncSession]:
    """Escopo de sessão async fora do ciclo de request: abre, popula o
    ContextVar, comita no fim (ou rollback na exceção), limpa. Para trabalho
    que precisa iterar um gerador dentro do escopo — o prelúdio do turno."""
    async with AsyncSessionLocal() as session:
        CurrentAsyncSessionContext.set(session)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            CurrentAsyncSessionContext.clear()


async def run_in_async_session(fn):
    async with async_session_scope():
        return await fn()
```

`except BaseException` (não `Exception`) porque `CancelledError` é
`BaseException` desde o Python 3.8 e precisa fazer rollback antes de subir.
`run_in_async_session` vira açúcar sobre o context manager — comportamento
idêntico, testes existentes continuam valendo.

Regra 3 do CLAUDE.md ganha uma frase: fora do request (corpo SSE, jobs,
eval), o escopo vem **deste módulo** — nunca de `AsyncSessionLocal()` direto.
`tests/unit/support/agent/test_domain_boundary.py` (ou um irmão) passa a
falhar se `src/domain/` importar `AsyncSessionLocal` ou `session_scope`: o
domínio lê a sessão do contexto, quem abre escopo é `app`/`console`/`evals`.

## 3. Port: `run()` devolve um `TurnRun` com duas fases explícitas

`src/support/agent/ports.py`:

```python
class TurnRun(Protocol):
    def prelude(self) -> AsyncIterator[AgentStreamChunk]:
        """Fase 1: gate → retrieve → (refuse | entrada do answer). Toca o banco
        via `deps`: consumir ATÉ O FIM dentro de um escopo de sessão, antes de
        `stream()`. Emite StepChunk ao vivo (started na entrada do nó,
        finished no update). Numa recusa, emite também o TextChunk canônico."""

    def stream(self) -> AsyncIterator[AgentStreamChunk]:
        """Fase 2: o restante — texto, tool calls, `answer finished`,
        SourcesChunk. Não toca o banco; deve rodar FORA de escopo de sessão.
        Chamar antes de `prelude()` esgotar é erro de programação
        (RuntimeError)."""


class TurnGraphPort(Protocol):
    def run(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> TurnRun: ...
```

`start()` deixa de existir no port, no runner, no fake e no harness de eval.
`run()` é síncrono: só monta o gerador do grafo e o emitter; nada executa até
`prelude()` ser iterado. A união `AgentStreamChunk` não muda.

## 4. Runner

`src/support/agent/graph/runner.py`:

### 4.1 Modo `debug` entra; `buffered`/`deferred` saem

`stream_mode=["updates", "messages", "debug"]`. O `TurnEmitter` ganha:

```python
_STEP_NODES = frozenset({"gate", "retrieve", "refuse", "answer"})

def on_debug(self, payload: dict) -> list[AgentStreamChunk]:
    """Só `type == "task"` (entrada de nó) e só o nome — o `input` do payload
    é o state inteiro e nunca sai daqui (regra 4)."""
    if payload.get("type") != "task":
        return []
    name = (payload.get("payload") or {}).get("name")
    return self.step_started(name) if name in _STEP_NODES else []
```

`task_result` é ignorado (o `finished` continua vindo do `update`, que é onde
os `signals` já estão escritos para o `detail`). `step_started` continua
idempotente, então o `update` de um nó cujo `task` não foi visto (fakes de
teste que não emitem `debug`) segue sintetizando o `started` como hoje.

`start()`, `buffered`, `deferred` e o ramo "F2" (`step_started("answer")` no
`except`) são removidos. A exceção adiada existia porque a fase 1 rodava
dentro do request e uma falha do estágio de resposta lá viraria 500 seco sem
trace; agora **toda** falha acontece no corpo e cai no `except` do
controller. O `answer started` no caminho de falha antes do primeiro token
já não precisa de caso especial: o `task` do nó `answer` o emitiu antes do
nó rodar.

### 4.2 `_TurnRun`

```python
class _TurnRun:
    def __init__(self, agen, emitter, signals): ...
    _prelude_done = False

    async def prelude(self):
        async for mode, payload in self._agen:
            if mode == "debug":
                chunks = self._emitter.on_debug(payload)
                for c in chunks: yield c
                if _is_task_of(payload, "answer"):
                    break                       # entrada REAL do nó de resposta (D3)
            elif mode == "updates":
                for c in self._emitter.on_update(payload): yield c
                if "refuse" in payload:
                    break
            elif _is_answer_event(payload):
                # Defensivo: não é esperado ver "messages" do answer antes do
                # seu `task`, mas se vier é a entrada — nada de texto se perde.
                for c in self._emitter.on_message(payload): yield c
                break
            # "messages" de outros nós (tokens do gate) são ignorados, como hoje.
        self._prelude_done = True

    async def stream(self):
        if not self._prelude_done:
            raise RuntimeError("stream() antes de prelude() esgotar")
        async for mode, payload in self._agen:
            if mode == "debug":
                chunks = self._emitter.on_debug(payload)   # answer/tools re-entrando: idempotente
            elif mode == "updates":
                chunks = self._emitter.on_update(payload)
            else:
                chunks = self._emitter.on_message(payload)
            for c in chunks:
                if isinstance(c, TextChunk): _mark_first_token(self._signals)
                yield c
        _mark_engine_end(self._signals)
        for c in self._emitter.finish(): yield c
```

Pontos a preservar do runner atual: `_is_answer_event` e o filtro de texto
em `on_message`; `_mark_first_token` só em `TextChunk`; `finish()` fecha o
`answer` se abriu e entrega `SourcesChunk` por último; `_config` com
`run_id`/`metadata` no topo; `_initial_state` com `preset_knowledge`.

Com `preset_knowledge` (eval adversarial) o primeiro `task` já é `answer`:
`prelude()` emite `answer started` e termina sem tocar o banco — o harness
continua chamando as duas fases sem caso especial.

Ordem observável de um turno substantivo, agora ao vivo:

```
task(gate)       → StepChunk(gate, started)
update(gate)     → StepChunk(gate, finished, {retrieve, degraded})
task(retrieve)   → StepChunk(retrieve, started)
update(retrieve) → StepChunk(retrieve, finished, {kept})
task(answer)     → StepChunk(answer, started)            ← prelude() termina aqui
── sessão fecha ──
messages(answer) → TextChunk..., ToolCall*...
update(tools)    → ToolCallResultChunk
...
finish()         → StepChunk(answer, finished), SourcesChunk
```

## 5. Actions

### 5.1 `OpenTurnAction` (renomeia `AnswerQuestionAction`)

`src/domain/conversations/actions/open_turn_action.py`. Mesmo corpo de hoje
**menos** a montagem de `deps` e o `await self.graph.start(...)`. Construtor
sem dependências. Devolve um DTO:

```python
# src/domain/conversations/dtos/opened_turn.py
@dataclass
class OpenedTurn:
    conversation_id: UUID
    question: str
    history: list[AgentMessage]
    draft: TurnTraceDraft
    signals: TurnSignals          # já pendurado em draft.signals
```

`_NearestDistance` sai daqui e vai para `RunTurnAction`. Testes de
`test_answer_question_action.py` e `test_answer_question_trace.py` são
renomeados e perdem os casos que afirmavam sobre o stream; o que testa
find-or-create, policy 404, título, ordem da recência e o draft continua.

### 5.2 `RunTurnAction` (nova)

`src/domain/conversations/actions/run_turn_action.py`:

```python
class RunTurnAction:
    """Dispara o grafo para um turno já aberto. Monta os `deps` AQUI, no
    escopo de sessão em que for chamada: os repositórios capturam a sessão do
    ContextVar no __init__ (regra 3), e a fase 1 roda no corpo SSE, fora da
    sessão do request (ADR-0020)."""

    def __init__(self, graph: TurnGraphPort, embeddings: EmbeddingsClient) -> None: ...

    def execute(self, turn: OpenedTurn) -> TurnRun:
        search = SearchKnowledgeBaseAction(embeddings=self.embeddings)
        deps = TurnDependencies(
            search=search,
            sections=ListKnowledgeSectionsAction(),
            refusal=build_out_of_scope_reply,
            nearest=_NearestDistance(search, DocumentChunkRepository()),
        )
        return self.graph.run(turn.question, turn.history, deps, turn.signals)
```

Síncrona (só composição). Teste unitário espelha
`test_harness_session_scope`: com um sentinela no `ContextVar`, o
`chunk_repo.session` do `search` que chegou ao grafo fake é o sentinela.

## 6. Controller

`ConversationController.ask`:

```python
user_email = CurrentRequestContext.get_user().email
run_id = data.run_id
turn = await OpenTurnAction().execute(data.question, data.conversation_id, user_email)
turn.draft.langsmith_run_id = run_id
graph = get_turn_graph_runner(run_id=run_id, user_hash=hash_email(user_email))
embeddings = get_embeddings_client()
ctx = RunContext(thread_id=str(turn.conversation_id), run_id=run_id)

async def event_source():
    yield encode(run_started(ctx))
    failed = False
    try:
        async with async_session_scope():
            run = RunTurnAction(graph, embeddings).execute(turn)
            async for chunk in run.prelude():
                ... captura + yield (mesmo laço de hoje)
        async for chunk in run.stream():
            ... captura + yield
    except Exception as exc:
        failed = True; draft.outcome = "error"; draft.error = ...; RUN_ERROR
    ... _absorb_engine_metrics, _persist_turn, RUN_FINISHED — inalterados
```

O laço de captura (`TextChunk` → `captured["text"]`, `SourcesChunk` →
`captured["citations"]`, `to_events` → `encode`) vira uma função local
usada pelas duas fases para não duplicar. `get_embeddings_client()` é
chamado no request (é um client HTTP, não captura sessão);
`SearchKnowledgeBaseAction` **não** é mais construída no controller — nasce
em `RunTurnAction`, dentro do escopo 2.

`RUN_STARTED` continua sendo o primeiro byte do corpo, agora **antes** de
qualquer trabalho do grafo — é o que faz a linha do tempo nascer vazia e
preencher ao vivo.

## 7. Frontend

Uma mudança, em `TurnTimeline.tsx` + `ChatPage.module.css`:

- `activity.length === 0` renderiza `<ol className={styles.timeline}
  aria-busy="true" aria-label="Andamento da resposta" />` — nenhum filho.
- `.timeline` ganha `min-height` igual a uma linha (`.timelineItem`), para a
  bolha não pular quando o primeiro passo chega.
- `.thinking` e suas regras (incluindo a de `prefers-reduced-motion`) são
  removidas; `@keyframes bounce` também, se nada mais usar.
- `TurnTimeline.test.tsx`: o caso "sem atividade mostra os pontos" vira
  "sem atividade renderiza a lista vazia e ocupada (`aria-busy`)".

`useAskStream`, `agui.ts`, `MessageBubble`, `ChatPage` não mudam: o status
`thinking` continua até o primeiro token e o `Composer` continua desabilitado
durante o turno. `demoStream.ts` já simula atrasos entre passos e passa a
refletir o comportamento real.

## 8. Falhas

| onde | antes (spec 04/09) | agora |
|---|---|---|
| body inválido / sem cookie / `threadId` alheio | 422 / 401 / 404 | **igual** (escopo 1) |
| gravar conversa ou pergunta falha | 500, rollback | **igual** (escopo 1) |
| gate, retrieve ou refuse quebram | 500 sem stream; pergunta desfeita; **sem trace** | `RUN_ERROR` genérico depois dos passos já emitidos; pergunta **gravada**; trace `outcome=error` com `gate_*`/`retrieval_*` do que rodou; resposta não persistida |
| nó `answer` quebra antes do 1º token | `RUN_ERROR` (exceção adiada) | `RUN_ERROR`, sem mecanismo de adiamento — cai no mesmo `except` |
| estágio de resposta quebra no meio | `RUN_ERROR`, trace, resposta não persistida | **igual** |
| tool falha | `TOOL_CALL_RESULT status=error`, run segue | **igual** |
| cliente desconecta no prelúdio | (não existia: prelúdio rodava no request) | `CancelledError` fecha o escopo 2 com rollback; sem trace, como numa desconexão no stream |
| stream cortado sem `RUN_FINISHED` | frontend → "conexão interrompida" | **igual** |

A linha "gate/retrieve quebram" é a única mudança de comportamento visível, e
é uma melhoria: o usuário vê o erro na bolha (com os passos que rodaram) em
vez de um 500 sem contexto, e o turno quebrado fica em `agent_traces` — a
mesma razão que o ADR-0016 (revisão I3) já dava para adiar a falha do
estágio de resposta, agora valendo para o turno inteiro. O `retry` do
frontend continua gravando outra pergunta, como já fazia.

## 9. Testes

**Unit — `session_scope`** (`tests/unit/support/core/test_session_scope.py`):
- `async_session_scope` seta o `ContextVar` dentro e limpa no `finally`,
  inclusive quando o corpo levanta `CancelledError`; `run_in_async_session`
  continua com os testes atuais.

**Unit — runner** (`tests/unit/support/agent/graph/test_runner.py`, reescrita
dos testes de fase):
- `prelude()` emite `gate started` **antes** de `gate finished` como chunks
  separados (hoje saem juntos) — a `search` fake registra que rodou depois do
  `gate finished` e antes do `retrieve finished`.
- `prelude()` termina na entrada do `answer` **antes** do modelo responder: o
  modelo fake bloqueia num `asyncio.Event`; o teste esgota `prelude()` com o
  evento ainda fechado, depois libera e consome `stream()`.
- Recusa: `prelude()` emite `refuse started/finished` + texto e termina;
  `stream()` só entrega `SourcesChunk` vazio.
- `preset_knowledge`: `prelude()` emite só `answer started`; `search` nunca
  roda.
- Falha no `retrieve` sobe de `prelude()`; falha do modelo antes do 1º token
  sobe de `stream()`, com `answer started` já emitido pelo `prelude()`.
- `stream()` antes de `prelude()` esgotar → `RuntimeError`.
- `on_debug`: `task` de nó desconhecido/`tools` não emite; `task_result` não
  emite; o chunk não contém nada além de `name`/`phase` (o `input` do payload
  não vaza).
- Os testes de `TurnEmitter` (tool calls, args allowlist, status) não mudam.

**Unit — Actions**:
- `OpenTurnAction`: os casos atuais de conversa/policy/recência/draft, sem
  os de stream.
- `RunTurnAction`: monta `deps` com a sessão corrente (sentinela) e repassa
  `question`/`history`/`signals` ao `graph.run`.
- Fronteira: `src/domain/` não importa `AsyncSessionLocal` nem
  `session_scope`.

**Integration — `tests/integration/api/`** (fakes em `tests/fakes/`):
- `FakeTurnGraph.run()` devolve um `FakeTurnRun`: `prelude()` emite `gate`/
  `retrieve` conforme a configuração (ou `refuse` + texto) e `answer started`;
  `stream()` emite texto, `answer finished`, `SourcesChunk`. Preenche
  `signals` como hoje.
- **Escopos**: um fake que grava `CurrentAsyncSessionContext.get()` em
  `prelude()` e em `stream()` — o primeiro é uma sessão aberta, diferente da
  do request (que já fechou); o segundo é `None`.
- **Ao vivo** não é testável por aqui: o `ASGITransport` do `httpx` bufferiza
  o corpo inteiro antes de devolver, então a ordem temporal fica invisível. A
  prova de que o prelúdio não espera o modelo é o teste unitário do runner
  (`asyncio.Event`); a checagem end-to-end é manual com `curl -N` (seção 12).
- **Falha no prelúdio**: fake que quebra em `prelude()` → `RUN_ERROR` sem
  `RUN_FINISHED`, `messages` tem a pergunta e não a resposta,
  `agent_traces` tem a linha com `outcome=error`.
- Os testes existentes (sucesso, recusa, threadId reusado, 404, 422, falha no
  stream, trace) migram para o fake novo sem mudar asserções.

**Eval** (`tests/unit/evals/test_harness_session_scope.py`): continua; o
harness passa a consumir `prelude()` e `stream()` dentro do escopo que já
abre para a corrida inteira.

**Frontend**: `TurnTimeline.test.tsx` (estado vazio); o resto inalterado.

## 10. Documentação

- **ADR-0020** — "Fase 1 do turno roda no corpo SSE, em escopo de sessão
  próprio". Resumo no topo (Decisão / Aplica-se quando / Regra prática).
  Substitui a seção "A restrição de sessão e o consumo em duas fases" do
  ADR-0016 quanto ao *lugar* (as duas fases continuam existindo; o critério de
  corte passa a ser o `task` do nó `answer`); registra D2 (falha do prelúdio
  vira `RUN_ERROR` com pergunta gravada) e D6 (duas Actions no endpoint).
  Torna obsoleta a seção 8 da spec de 04/09 e a consequência descrita no
  ADR-0019 ("chegam numa rajada").
- `docs/adr/README.md`: linha do 0020; status do 0016 vira "*consumo em duas
  fases revisado pelo 0020*".
- `CLAUDE.md`: bullet "Agente de IA" ("consumido em duas fases via
  `TurnGraphPort`" → "consumido em dois escopos de sessão via
  `TurnGraphPort.run()`; ver ADR-0016 e ADR-0020"); regra 3 ganha a frase
  sobre `session_scope.py`; lista de ADRs.
- `docs/architecture.md`: parágrafos "Consumo em duas fases" e "Contrato de
  saída: AG-UI" (remover a frase da rajada), trecho do trace que cita
  `AnswerQuestionAction`.
- `frontend/src/features/ops/architectureMap.ts`, **no mesmo commit do
  controller**: caixa `runner` → label "Dois escopos de sessão", descrição
  nova, `files` + `src/support/core/session_scope.py` e
  `src/domain/conversations/actions/run_turn_action.py`.
- Spec de 04/09, seção 8, e spec do LangGraph de 01/09, seção 5: nota
  apontando para esta spec.

## 11. Sequência de corte

Cada item é um commit verde (`pytest`, `npm test`, `tsc`, `alembic check`).

1. `session_scope.py`: `async_session_scope` + `run_in_async_session` por
   cima; testes.
2. `ports.py` (`TurnRun`, `run()`) + `runner.py` (modo `debug`, `_TurnRun`,
   remoção de `start`/`buffered`/`deferred`) + testes do runner, **junto com**
   `tests/fakes/fake_turn_graph.py` (`run()`/`FakeTurnRun`), `evals/runner.py`
   e `test_harness_session_scope.py` — nada mais chama `start()` depois deste
   commit. A Action ainda chama `graph.start()` até o item 3; para o commit
   ficar verde, a Action passa a chamar `run()` + `prelude()`/`stream()` de
   forma transitória aqui (ainda dentro do request), e o item 3 desfaz isso.
3. `OpenTurnAction` + `OpenedTurn` + `RunTurnAction` + testes; teste de
   fronteira do domínio para sessão.
4. Controller + testes de integração + `architectureMap.ts`.
5. Frontend: `TurnTimeline` + CSS + teste.
6. ADR-0020, README dos ADRs, `CLAUDE.md`, `docs/architecture.md`, notas nas
   duas specs anteriores.

Backend e frontend continuam falando o mesmo contrato; o deploy não precisa
ser conjunto (o frontend antigo com os pontos funciona contra o backend novo,
só mostra os pontos por menos tempo).

## 12. Critérios de aceite

- No navegador, uma pergunta substantiva mostra "Entendendo a pergunta"
  **pulsando** antes de concluir, depois "Buscando na base" pulsando, depois
  "· N trechos", depois "Respondendo" **antes** do primeiro token. Em nenhum
  momento aparecem os três pontos.
- `curl -N` com um `RunAgentInput` válido imprime `RUN_STARTED` e
  `STEP_STARTED gate` imediatamente, e `STEP_FINISHED gate` só depois de um
  intervalo perceptível (a latência do gate).
- Uma recusa mostra os dois primeiros passos ao vivo, depois "Nada na base
  cobre essa pergunta" + texto canônico.
- Com o fake que quebra no prelúdio: `RUN_ERROR`, pergunta em `messages`,
  linha em `agent_traces` com `outcome=error`.
- Teste de integração prova que `stream()` roda com
  `CurrentAsyncSessionContext.get() is None`.
- Nenhum evento carrega o `input` do nó, conteúdo de tool, `page_id` ou
  e-mail.
- Sem migration, sem dependência nova. `pytest`, `npm test`, `tsc`,
  `alembic check` e `prospector` verdes (os 8 achados pré-existentes de
  `ports.py`/`runner.py` podem cair com a remoção de `start()`; não podem
  subir).
