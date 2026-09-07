# O turno do oráculo fala `astream_events`: `StreamEvent` do LangChain no fio

Data: 2026-09-07
Origem: brainstorm Duanne <> Claude, 07/09/2026.
Substitui: o **contrato** do ADR-0019 (eventos AG-UI) — via ADR-0021, a ser
escrito na sequência de corte, antes da implementação. O transporte SSE
(ADR-0009) e o consumo em duas fases no corpo SSE (ADR-0020) são mantidos.

## Contexto

Hoje `POST /conversations/ask` recebe um `RunAgentInput` do AG-UI e devolve
eventos AG-UI (`RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`, `TEXT_MESSAGE_*`,
`CUSTOM oracle.step`/`oracle.sources`, `RUN_FINISHED`/`RUN_ERROR`) em
`data: {json}`. Por baixo, `src/support/agent/graph/runner.py` consome o grafo
com `astream(stream_mode=["updates", "messages", "debug"])` e um `TurnEmitter`
sintetiza sete dataclasses de chunk (`TextChunk`, `StepChunk`,
`ToolCall*Chunk`, `SourcesChunk`); `src/app/api/streaming/ag_ui_encoder.py`
traduz cada chunk em um ou mais eventos do protocolo. O frontend desfaz a
tradução em `frontend/src/lib/api/agui.ts` e entrega `AskEvent` ao hook.

O LangChain tem um formato próprio de evento de streaming: o **`StreamEvent`**
(`langchain_core.runnables.schema.StandardStreamEvent`), produzido por
`Runnable.astream_events(version="v2")`:

```python
{"event": "on_chat_model_stream", "name": "ChatAnthropic", "run_id": "...",
 "tags": [...], "metadata": {...}, "parent_ids": [...], "data": {"chunk": ...}}
```

Nomes seguem `on_[chain|chat_model|tool|...]_(start|stream|end)`. Um
`CompiledStateGraph` do LangGraph aceita `stream_mode` em `astream_events` (via
`**kwargs`, repassados ao `astream` do grafo); os chunks de cada modo chegam
como `on_chain_stream` do grafo raiz, com `data.chunk == (modo, payload)`.

Referência do método (assinatura, tabela de eventos por tipo de runnable,
filtros `include_*`/`exclude_*`, versões `v1`/`v2`/`v3`): `as_stream.md`, cópia
da página `Runnable.astream_events` da referência do `langchain_core`
(https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events).
Esta spec usa **`version="v2"`**: é o schema `StreamEvent` acima, o que o
brainstorm pediu no fio. `v3` (protocolo por blocos de conteúdo, beta) fica
fora até estabilizar; `v1` está a caminho da depreciação.

### O que o brainstorm decidiu

1. **O fio passa a ser o `StreamEvent`.** Cada bloco SSE vira
   `event: <nome do evento>\ndata: <StreamEvent em JSON>\n\n`. Não há mais
   eventos sintéticos do AG-UI nem um segundo vocabulário no meio do caminho.
2. **`stream_mode=["values", "updates"]`, sem `custom`.** Os dois modos são
   emitidos no fio; o frontend consome só `updates` (e os eventos de nó, modelo
   e tool). `values` vai pelo fio por fidelidade ao `astream_events`, e mais
   nada.
3. **Frontend acompanha.** `agui.ts` vira o parser do novo formato. O
   `AskEvent` interno, o hook e a UI não mudam.
4. **Payloads redigidos, não crus.** O `StreamEvent` cru carrega o state inteiro
   (o `knowledge` recuperado), o prompt completo (`on_chat_model_start`) e o
   conteúdo bruto que a tool devolveu ao modelo (`on_tool_end`). A regra 4 do
   CLAUDE.md continua valendo: o runner aplica uma **allowlist de eventos** e
   uma **projeção fixa** sobre `data` antes de qualquer evento cruzar o port.
5. **Body do request espelha `astream_events(input, config)`.** Sai o
   `RunAgentInput`; entra `{"input": {...}, "config": {...}}` com os campos
   que o LangChain já usa (`run_id`, `configurable.thread_id`). Isto é a
   leitura do "troca por StreamEvent, que tem os parâmetros corretos do
   `astream_events`" do brainstorm — o `StreamEvent` é o **retorno** do
   método, então o body toma emprestado os **parâmetros**. É o único ponto
   desta spec que fica explicitamente marcado para confirmação na revisão.

### Por que não mandar o evento cru

Sonda feita em 07/09 sobre o grafo real (`build_turn_graph()` com modelos
fake) mostra, no cru: `on_chain_start` de cada nó com `data.input` = state
inteiro; `on_chain_end` de `retrieve` com os `KnowledgeSnippet`;
`on_chat_model_start` com o `SystemMessage` e o contexto embrulhado;
`on_tool_end` com a `ToolMessage` completa; `values` com tudo isso somado a
cada super-step. Além dos nós, chegam as arestas condicionais (`route_entry`,
`should_retrieve`, `has_grounding`, `tools_condition`), o nó `__start__` e os
runnables internos do `with_structured_output` do gate. Nada disso pode sair
para o cliente: os runnables internos por ruído, o resto por regra 4.

### Por que não os filtros nativos do método

`astream_events` aceita `include_names`, `include_types`, `include_tags` e os
`exclude_*` correspondentes. Eles filtram **por nome, tipo ou tag do runnable**
e nada mais — não sabem dizer "só `on_chat_model_stream` quando
`metadata.langgraph_node == "answer"`", nem "só nós cujo `name` coincide com o
`langgraph_node`" (é o que separa `gate` da aresta `should_retrieve`, que roda
com o mesmo `langgraph_node`). Também não tocam em `data`, e a projeção é a
parte que importa para a regra 4. Como o redator precisa existir de qualquer
jeito e é a única barreira que garante o que sai, a allowlist mora inteira
nele; os filtros nativos não são usados, para não haver duas listas do mesmo
assunto em lugares diferentes.

## Decisão

- **Runner** troca `astream(...)` por
  `astream_events(input, config=..., version="v2", stream_mode=["values", "updates"])`.
  O `TurnEmitter` e os sete chunks morrem; o port passa a emitir um único
  dataclass, `GraphEvent`, que espelha o `StreamEvent` campo a campo e já sai
  **redigido**.
- **Corte da fase 1 (ADR-0020)** vira o `on_chain_start` do nó `answer` (a
  entrada real do nó, papel que o `task` do modo `debug` fazia) ou o
  `on_chain_end` do nó `refuse`. O modo `debug` deixa de existir aqui.
- **Camada `app`** serializa `GraphEvent` em `event:`/`data:` e sintetiza um
  único evento próprio, `on_chain_error`, para falha no meio do stream. O body
  do endpoint é um schema Pydantic novo, sem `ag_ui`.
- **Frontend** parseia `event:` + `data:`, valida o `StreamEvent` e traduz
  para o `AskEvent` de sempre.
- **`ag-ui-protocol` sai do `pyproject.toml`** — nada mais o importa (regra 10:
  remoção, registrada aqui e no ADR-0021).

## Fora de escopo

- `stream_mode="custom"` e `get_stream_writer()`: fora, por decisão.
- `stream_mode="messages"`: os tokens vêm de `on_chat_model_stream`; o modo
  não é necessário.
- Checkpointer, mudanças nos nós, nas arestas, nas tools ou nos prompts do grafo.
- Persistência (`messages`, `agent_traces`) e a página de ops: continuam
  guardando o que guardam hoje. Nada da linha do tempo é persistido.
- Aparência da UI: a linha do tempo, o texto e as fontes renderizam igual.
- O adaptador oficial LangGraph ↔ AG-UI e o `@ag-ui/client`: saem junto com
  o protocolo.

## 1. Contrato do endpoint

### 1.1 Entrada

`POST /conversations/ask`, `Content-Type: application/json`,
`Accept: text/event-stream`. Body espelha os parâmetros de
`astream_events(input, config)`:

```json
{
  "input": { "question": "como funciona a renovação?" },
  "config": {
    "run_id": "<uuid>",
    "configurable": { "thread_id": "<uuid>" }
  }
}
```

Regras, todas validadas **antes** de abrir o stream (falha é HTTP 422, nunca
evento):

| campo | regra |
|---|---|
| `input.question` | string obrigatória, não vazia depois de `strip()`. É a pergunta. |
| `config.run_id` | UUID obrigatório, normalizado para a forma canônica. Vira `run_id` do LangSmith e `langsmith_run_id` do trace. |
| `config.configurable.thread_id` | UUID obrigatório, normalizado. É o id da conversa: existe e é do usuário → continua; não existe → cria com esse id; é de outro usuário → **404** (`ConversationAccessPolicy`, ADR-0017). |
| outras chaves em `input`, `config` ou `configurable` | aceitas e ignoradas (`tags`, `metadata`, `recursion_limit`, …). O servidor monta o `config` real; o cliente não injeta `configurable` no grafo. |

Schema: `src/app/api/requests/stream_events_request.py`, classe
`StreamEventsRequest` (Pydantic v2, regra 7), com as propriedades `question`,
`conversation_id` e `run_id` que o controller consome hoje. O
`run_agent_request.py` é removido.

### 1.2 Saída

`200`, `text/event-stream`. Cada bloco SSE:

```
event: on_chat_model_stream
data: {"event":"on_chat_model_stream","name":"ChatAnthropic","run_id":"…","tags":["seq:step:1"],"metadata":{"langgraph_node":"answer","langgraph_step":3,"thread_id":"…","ls_provider":"anthropic","ls_model_name":"…"},"parent_ids":["…"],"data":{"chunk":{"content":"Renov","id":"lc_run--…"}}}

```

`data:` é o `StreamEvent` serializado, com **todos os sete campos sempre
presentes** (`event`, `name`, `run_id`, `tags`, `metadata`, `parent_ids`,
`data`). A linha `event:` repete `data.event` — é o que o brainstorm pediu e o
que permite `EventSource`/parsers filtrarem por nome sem abrir o JSON.

**Allowlist de eventos** (nada fora dela sai do runner), na ordem típica:

| momento | `event` | `name` | `data` (redigido) |
|---|---|---|---|
| abertura do corpo | `on_chain_start` | `LangGraph` | `{}` |
| entrada de nó `gate` / `retrieve` / `refuse` / `answer` | `on_chain_start` | nó | `{}` |
| chunk do modo `updates` | `on_chain_stream` | `LangGraph` | `{"chunk": ["updates", {"<nó>": projeção(update)}]}` |
| chunk do modo `values` | `on_chain_stream` | `LangGraph` | `{"chunk": ["values", projeção(state)]}` |
| saída de nó `gate` / `retrieve` / `refuse` / `answer` | `on_chain_end` | nó | `{"output": projeção(saída do nó)}` |
| token do modelo (só no nó `answer`) | `on_chat_model_stream` | classe do modelo | `{"chunk": {"content": str, "id": str}}` — `content` é o texto do `AIMessageChunk` já achatado (Anthropic entrega lista de blocos, OpenAI string; `_text_of` de hoje). Chunks cujo texto achatado é vazio (só `tool_call_chunks`, ou o vazio final do provedor) são descartados. |
| tool começa | `on_tool_start` | nome da tool | `{"input": args}` só para `web_search`; `{}` para as demais (`fetch_notion_page`: o `page_id` não cruza o port) |
| tool termina | `on_tool_end` | nome da tool | `{"output": {"status": "ok" \| "error", "tool_call_id": str}}`. **Nunca o conteúdo da tool.** |
| tool levantou exceção | `on_tool_error` | nome da tool | `{"output": {"status": "error", "tool_call_id": str}}` — mesma forma do `on_tool_end`; a mensagem do erro não sai |
| fim | `on_chain_end` | `LangGraph` | `{"output": {"outcome": str, "citations": [...]}}` |
| falha durante o stream | `on_chain_error` | `LangGraph` | `{"error": "erro ao gerar a resposta"}` — sintetizado pela camada `app`, terminal. **Sem `on_chain_end` depois.** |

Descartados pelo runner: `__start__` e arestas condicionais (`route_entry`,
`should_retrieve`, `has_grounding`, `tools_condition`); `on_chain_*` do nó
`tools` (as tool calls contam a história); `on_chain_stream` **de nós** (repete
o `on_chain_end`); `on_chat_model_start`/`on_chat_model_end`;
`on_chat_model_stream` de nós que não sejam `answer` (structured output do
gate); qualquer runnable interno. Critério mecânico: um evento de nó só passa se
`name in {gate, retrieve, refuse, answer}` **e** `metadata.langgraph_node ==
name`; eventos de modelo só passam com `event == "on_chat_model_stream"` e
`metadata.langgraph_node == "answer"`; eventos de tool passam com
`metadata.langgraph_node == "tools"`; eventos do raiz passam com
`parent_ids == []`.

**Projeção do state** (`projeção(d)`), aplicada a saídas de nó, a cada valor
dentro de um chunk `updates` e ao snapshot de `values`:

| chave no state | no fio |
|---|---|
| `retrieve`, `degraded` | copiadas |
| `knowledge` | vira `kept: len(knowledge)` |
| `answer` | copiada (é o texto canônico da recusa; no caminho de resposta a chave não existe no state) |
| `citations` | copiada como lista de `{source_type, title, url, snippet}` — sem `page_id` |
| `outcome` | copiada |
| `question`, `history`, `preset_knowledge`, `search_query`, `messages` | **removidas** |

`messages` é o que carrega prompt, knowledge embrulhado e `ToolMessage`s — cai
inteira. `search_query` cai por ser dispensável, não por risco. O update do nó
`tools` (só `messages`) vira `{}`.

**Metadata** passa por allowlist: `langgraph_node`, `langgraph_step`,
`thread_id`, `ls_provider`, `ls_model_name`. `user_hash`, `langgraph_path`,
`langgraph_triggers`, `langgraph_checkpoint_ns` e o resto ficam de fora.
`tags` vai como vem (só rótulos `seq:step:N`/`graph:step:N`). O runner garante
`metadata.thread_id` em todo evento emitido: é como o cliente descobre o id da
conversa a partir do `on_chain_start` do raiz (papel do `threadId` do
`RUN_STARTED`). O `run_id` do evento raiz é o `config.run_id` do request — o
mesmo run do LangSmith.

**Regras de passos**, preservadas do ADR-0019:

- `answer` abre **uma vez** e fecha **uma vez**, mesmo com tool loop. O runner
  deixa passar só o **primeiro** `on_chain_start` do `answer` e **segura** o
  `on_chain_end` do `answer`, emitindo o último deles imediatamente antes do
  `on_chain_end` do raiz. Nenhum evento é inventado: o que sai é o evento real
  da última saída do nó, atrasado.
- `refuse` emite `on_chain_start`/`on_chain_end`; o texto canônico chega no
  chunk `["updates", {"refuse": {"answer": "..."}}]` (e repetido no `output` do
  `on_chain_end` do nó, pela projeção). `citations` vem vazio.
- Com `preset_knowledge` (eval adversarial) não há gate nem retrieve; só
  `answer`.

## 2. Ports: um único `GraphEvent`

`src/support/agent/ports.py`: os sete chunks (`TextChunk`, `SourcesChunk`,
`StepChunk`, `ToolCallStartChunk`, `ToolCallArgsChunk`, `ToolCallEndChunk`,
`ToolCallResultChunk`) e a união `AgentStreamChunk` são removidos. Entra:

```python
@dataclass
class GraphEvent:
    """Um StreamEvent do astream_events, já REDIGIDO pelo runner (regra 4).
    Espelha `langchain_core.runnables.schema.StandardStreamEvent` campo a
    campo, sem importar langchain — o domínio consome isto."""

    event: str
    name: str
    run_id: str
    tags: list[str]
    metadata: dict
    parent_ids: list[str]
    data: dict

    @property
    def node(self) -> str | None:
        return self.metadata.get("langgraph_node")

    @property
    def is_root(self) -> bool:
        return not self.parent_ids
```

`data` carrega `Citation` (value object do domínio) onde há citações — o port
continua tipado, e quem serializa é a camada `app`. Duas funções puras no
mesmo módulo, para quem precisa do conteúdo sem conhecer a allowlist:

```python
def text_of(event: GraphEvent) -> str:
    """Texto que vira resposta: `on_chat_model_stream` do answer e o `answer`
    do update de `refuse`. "" para qualquer outro evento."""

def citations_of(event: GraphEvent) -> list[Citation] | None:
    """As fontes do turno: só no `on_chain_end` do raiz. None nos demais."""
```

`TurnRun.prelude()`/`stream()` passam a ser `AsyncIterator[GraphEvent]`. O
docstring de `TurnRun` e `TurnGraphPort` muda de "StepChunk/TextChunk" para
"GraphEvent". `TurnGraphPort.run()` ganha `thread_id: str | None = None`
(entra em `configurable.thread_id` e, por consequência, em `metadata`).
Consumidores: `conversation_controller.py`, `evals/runner.py` (troca
`isinstance(chunk, TextChunk)` por `text_of(event)`), `tests/fakes/fake_turn_graph.py`.

## 3. Runner: `astream_events` + redação

`src/support/agent/graph/runner.py`:

```python
agen = self._graph.astream_events(
    _initial_state(question, history, knowledge),
    config=self._config(deps, signals, extra_config),
    version="v2",
    stream_mode=["values", "updates"],
)
```

`stream_mode` viaja em `**kwargs` até o `astream` do grafo — é o mecanismo
documentado, não um atalho. Nenhum `include_*`/`exclude_*` é passado (ver
"Por que não os filtros nativos do método").

Um `EventRedactor` (nome interno; um por run) substitui o `TurnEmitter`:

- `redact(raw: StreamEvent) -> GraphEvent | None` — `None` quando o evento
  está fora da allowlist (seção 1.2). Nunca lê `data.input` de nó ou de
  modelo; lê `data.output`/`data.chunk` só para projetar.
- Guarda: `answer_started: bool` (dedupe do `on_chain_start`) e
  `pending_answer_end: GraphEvent | None` (o `on_chain_end` segurado).
- `flush_before_root_end()` devolve o `on_chain_end` do `answer` segurado, se
  houver.
- `citations` finais: lidas do `output.citations` do `on_chain_end` do raiz
  (state final), não acumuladas por update.

`_TurnRun.prelude()` itera o gerador, redige, faz `yield` do que passar e
**para** quando o evento redigido é `on_chain_start` com `name == "answer"`
(depois de emiti-lo) ou `on_chain_end` com `name == "refuse"` (depois de
emiti-lo). `stream()` continua o mesmo gerador (o `break` não fecha o
`astream_events`, como hoje), marca `first_token_ms` no primeiro
`on_chat_model_stream` com `content` não vazio e `engine_ms` ao fim, e antes de
emitir o `on_chain_end` do raiz emite o `on_chain_end` do `answer` segurado.

Nada muda em `nodes.py`, `edges.py`, `builder.py`, `state.py`, `tools.py`. O
docstring de `answer_node` que cita `stream_mode="messages"` é atualizado.

## 4. Camada `app`

### 4.1 `src/app/api/requests/stream_events_request.py`

`StreamEventsRequest(BaseModel)` com `input: _Input` (`question: str`) e
`config: _Config` (`run_id: str`, `configurable: _Configurable` com
`thread_id: str`); validadores normalizam os UUIDs (mesma
`_canonical_uuid` de hoje, movida junto) e recusam `question` vazia.
`model_config = ConfigDict(extra="ignore")` nos três níveis. Propriedades
`question: str`, `conversation_id: UUID`, `run_id: str`.

### 4.2 `src/app/api/streaming/stream_event_encoder.py`

Substitui `ag_ui_encoder.py`. Função pura + um sintetizador:

```python
CONTENT_TYPE = "text/event-stream"

def encode(event: GraphEvent) -> str:
    """`event: <event.event>\\ndata: <json>\\n\\n`. Citation vira
    {source_type, title, url, snippet}; qualquer outro dataclass, asdict."""

def error_event(run_id: str, thread_id: str, message: str) -> GraphEvent:
    """O único evento que não vem do grafo: on_chain_error do raiz, com
    data={"error": message}. metadata carrega thread_id."""
```

`json.dumps(..., ensure_ascii=False, default=_json_default)`; o `default`
conhece `Citation` (sem `page_id`) e dataclasses genéricos. Sem dependência
externa.

### 4.3 Controller

Mesmos três escopos do ADR-0020. Mudanças:

- Body: `StreamEventsRequest`. `get_turn_graph_runner(run_id=..., user_hash=...,
  thread_id=str(turn.conversation_id))`.
- `capture(event)` acumula `text_of(event)` e guarda `citations_of(event)`
  quando não for `None`.
- O **`on_chain_end` do raiz é retido**: o controller não o escreve ao chegar;
  persiste o turno (`_persist_turn`) e só então o emite — é o que o
  `RUN_FINISHED` fazia (a sidebar recarrega com a conversa já gravada). Em
  falha, emite `error_event(...)` e **não** emite o `on_chain_end` retido.
- Não há mais "primeiro byte antes do grafo" sintetizado: o `on_chain_start`
  do raiz é o primeiro evento que o `astream_events` produz e sai assim que o
  escopo de sessão abre — antes do gate rodar.

## 5. Frontend

### 5.1 `frontend/src/lib/api/sse.ts`

`parseSSEData` passa a devolver `{ event: string | null; data: string }` por
bloco (lê a linha `event:`; continua ignorando `id:`/`retry:` e unindo
múltiplas `data:`). Nome: `parseSSE`. Testes ajustados.

### 5.2 `frontend/src/lib/api/streamEvents.ts` (substitui `agui.ts`)

- `type StreamEvent = { event: string; name: string; run_id: string; tags: string[]; metadata: Record<string, unknown>; parent_ids: string[]; data: Record<string, unknown> }`.
- `parseStreamEvent(data: string): StreamEvent | null` — JSON inválido ou sem
  `event`/`name`/`run_id` string → `null` (tolerância a eventos futuros).
- `buildAskBody(question, threadId?)` monta `{input, config}` da seção 1.1
  (mint de `thread_id` quando não há conversa, `run_id` sempre novo).
- `toAskEvents(events)` traduz para o `AskEvent` **existente**:

| `StreamEvent` | `AskEvent` |
|---|---|
| `on_chain_start`, raiz | `run_started {conversationId: metadata.thread_id}` |
| `on_chain_start`, nó | `step started {name}` |
| `on_chain_end`, nó `gate`/`retrieve` | `step finished {name, detail: data.output}` (`{retrieve, degraded}` / `{kept}`) |
| `on_chain_end`, nó `refuse`/`answer` | `step finished {name}` sem detail |
| `on_chain_stream` `["updates", {refuse: {answer}}]` | `token {text: answer}` |
| `on_chain_stream` `["values", …]` | ignorado (decisão 2) |
| `on_chat_model_stream` | `token {text: data.chunk.content}` se não vazio |
| `on_tool_start` | `tool_call_start {id: run_id, name}` e, se `data.input` presente, `tool_call_args {id, delta: JSON.stringify(input)}`; sempre `tool_call_end {id}` |
| `on_tool_end` | `tool_call_result {id: run_id, status: data.output.status}` |
| `on_chain_end`, raiz | `sources {citations: data.output.citations}` e depois `done` |
| `on_chain_error` | `error {message: data.error}` (terminal) |

A tool é identificada pelo `run_id` do evento de tool (`on_tool_start` e
`on_tool_end` da mesma execução compartilham o `run_id`). `tool_call_args` +
`tool_call_end` são emitidos em sequência para que o `ToolItem` do hook parseie
os args como hoje, sem mudar o reducer.

`conversations.ts` usa `buildAskBody`, `parseSSE` e `toAskEvents`.
`types.ts`: só o comentário do `AskEvent` muda ("tradução do `StreamEvent`
em `lib/api/streamEvents.ts`, ADR-0021"). `demoStream.ts`, `useAskStream.ts` e
componentes: intocados.

## 6. Falhas

| onde | o que o cliente vê |
|---|---|
| validação do body, 401/404 | status HTTP, sem stream (igual a hoje) |
| falha em `prelude()` (gate/retrieve/refuse) | os eventos que houve + `on_chain_error` |
| falha em `stream()` (provider, tool) | idem, com os tokens que saíram |
| falha ao persistir | `on_chain_end` do raiz sai mesmo assim (resposta já entregue); erro só no log |

`on_chain_error` é sempre o último bloco quando aparece. O trace grava
`outcome="error"` e `error` truncado, como hoje.

## 7. Dependências

- `ag-ui-protocol` removido de `pyproject.toml` e `uv.lock`. Nada importa
  `ag_ui` depois desta spec.
- Nenhuma dependência nova: `astream_events` e `StreamEvent` já vêm de
  `langchain-core`/`langgraph` instalados.

## 8. Testes

Backend (todos os arquivos abaixo são reescritos, não estendidos):

- `tests/unit/support/agent/graph/test_runner.py`: fases (prelúdio termina no
  `on_chain_start` do `answer` / no `on_chain_end` do `refuse`; retrieval roda
  no prelúdio e não no stream; `first_token_ms`/`engine_ms`), allowlist (nenhum
  evento de aresta, `__start__`, `tools`, `on_chat_model_start`, `on_chain_stream`
  de nó), projeção (nenhum `messages`, `knowledge`, `question`, `history`,
  `search_query` em `data` de evento nenhum — teste percorre `data`
  recursivamente), `answer` abre uma vez e fecha uma vez com tool loop, tool
  `on_tool_start` com `input` só para `web_search`, `on_tool_end` só com
  status, `metadata` allowlisted e com `thread_id`, `citations_of` no raiz.
- `tests/unit/app/api/streaming/test_stream_event_encoder.py`: formato
  `event:`/`data:`, sete campos, `Citation` sem `page_id`, `error_event`.
- `tests/unit/app/api/requests/test_stream_events_request.py`: body válido,
  UUIDs normalizados, `question` vazia, `thread_id`/`run_id` inválidos, extras
  ignorados.
- `tests/integration/api/test_ask_endpoint.py` e
  `test_ask_trace_persistence.py`: mesmos cenários, lendo o fio novo.
  `tests/fakes/ag_ui_stream.py` vira `tests/fakes/stream_events.py`
  (`ask_body`, `events(body) -> list[(event, dict)]`, `text_of`, `sources_of`).
  `tests/fakes/fake_turn_graph.py` emite `GraphEvent`s.
- `tests/unit/support/agent/test_domain_boundary.py`: o teste do `ag_ui` sai;
  entra `test_domain_and_graph_do_not_import_the_app_layer` (`src.app` não
  aparece em `src/domain/` nem em `src/support/agent/`), com o guard de "a
  lista casa com algo" apontando para `src/app/api/controllers/`.

Frontend:

- `sse.test.ts` (linha `event:`), `streamEvents.test.ts` (substitui
  `agui.test.ts`: parser, `buildAskBody`, `toAskEvents` em todos os ramos da
  tabela 5.2, `on_chain_error` terminal), `useAskStream.test.ts` sem mudança,
  `architectureMap.test.ts` (arquivos novos existem).

## 9. Documentação

- **ADR-0021** — "O turno é entregue como `StreamEvent` do `astream_events`",
  com `## Resumo`; marca o ADR-0019 como *contrato substituído pelo 0021*
  (regras 4 e ADR-0020 mantidas) no índice do `docs/adr/README.md`.
- `CLAUDE.md`: linha "Protocolo de UI" e lista de ADRs.
- `docs/architecture.md`: parágrafos "Consumo em duas fases" (corte pelo
  `on_chain_start`) e "Contrato de saída".
- `frontend/src/features/ops/architectureMap.ts`: caixa `ask` (label,
  descrição, `stream_events_request.py`, `stream_event_encoder.py`) e
  descrição da caixa `runner` (sem `debug`).
- Notas de "substituído por" no topo desta família de specs: 04/09 (AG-UI) e
  05/09 (turno ao vivo, onde o corte cita o `debug`).
- `docs/as_stream.md` (referência do método, cópia da página oficial) é
  versionado e citado pelo ADR-0021, citado pelo ADR-0021 e
  por esta spec. É a cópia local do que o ADR assume sobre o schema.

## 10. Sequência de corte

1. ADR-0021 + índice do README (antes do código, como manda o guia).
2. Ports: `GraphEvent`, `text_of`, `citations_of`; remoção dos chunks.
3. Runner: `astream_events`, `EventRedactor`, fases — TDD sobre
   `test_runner.py`.
4. Request + encoder + controller; fakes e testes de integração.
5. `evals/runner.py`.
6. Frontend: `sse.ts`, `streamEvents.ts`, `conversations.ts`, testes.
7. `architectureMap.ts`, `CLAUDE.md`, `architecture.md`, notas nas specs.
8. Remover `ag-ui-protocol`; `uv lock`; `pytest`, `prospector`,
   `npm test`, `alembic check`, `python -c "from main import app"`.

## 11. Critérios de aceite

- Um turno real com pergunta substantiva produz, nesta ordem:
  `on_chain_start LangGraph`, `on_chain_stream [values]` (state inicial, que a
  projeção reduz a `{"kept": 0}`), `on_chain_start gate`, `on_chain_end gate`,
  `on_chain_stream [updates {gate}]`, `on_chain_stream [values]`, idem para
  `retrieve`, `on_chain_start answer`, N × `on_chat_model_stream`, chunks de
  `updates`/`values` do answer, `on_chain_end answer`, `on_chain_end LangGraph`
  — e cada bloco tem `event:` igual a `data.event`. A ordem "fim do nó, depois
  `updates`, depois `values`" é a do LangGraph (sonda de 07/09), não uma
  escolha nossa.
- Nenhum bloco do fio contém `messages`, `knowledge`, `question`, `history`,
  `search_query`, `user_hash` ou conteúdo de tool. Teste unitário percorre
  `data` recursivamente para garantir.
- Recusa: `on_chain_start refuse` → `on_chain_end refuse` (fim do prelúdio) →
  chunk `updates` com o texto canônico → chunk `values` → `on_chain_end
  LangGraph` com `citations: []`; o texto fica gravado em `messages`.
- Tool loop: exatamente um `on_chain_start answer` e um `on_chain_end answer`;
  `on_tool_start web_search` com `input`; `on_tool_start fetch_notion_page`
  com `data == {}`; `on_tool_end` só com `status` e `tool_call_id`.
- Falha no meio: `on_chain_error` é o último bloco; não há `on_chain_end
  LangGraph`; a resposta não é persistida; o trace tem `outcome="error"`.
- `prelude()` termina antes do modelo responder (teste do `_BlockingChatModel`
  mantido) e o retrieval roda dentro dele.
- Frontend renderiza linha do tempo, tokens, tool calls e fontes como hoje,
  com `useAskStream.test.ts` intocado e verde.
- `grep -r ag_ui src tests evals frontend/src` vazio; `uv pip list` sem
  `ag-ui-protocol`.
