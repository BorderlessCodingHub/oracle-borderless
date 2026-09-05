# O turno do oráculo fala AG-UI: passos e tool calls visíveis na UI

Data: 2026-09-04
Origem: brainstorm Duanne <> Claude, 04/09/2026.
Substitui: ADR-0009 (contrato SSE do chat) — via ADR-0019, a ser escrito na
sequência de corte, antes da implementação.

## Contexto

O oráculo responde hoje por um contrato SSE caseiro em
`src/app/api/controllers/conversation_controller.py`: cinco eventos
(`conversation`, `token`, `sources`, `error`, `done`), parseados à mão em
`frontend/src/lib/api/sse.ts` e `conversations.ts`. Tudo o que o grafo faz entre
a pergunta e o primeiro token — gate, retrieval, recusa, tool calls — é
filtrado de propósito em `src/support/agent/graph/runner.py` e fica invisível
para quem pergunta. A tela conhece três momentos: "pensando" (indicador
genérico), "streaming" e "fontes" (bloco no fim).

**AG-UI** (Agent–User Interaction Protocol, https://docs.ag-ui.com) é um
contrato aberto de eventos sobre HTTP + SSE para ligar agentes a interfaces. O
cliente faz `POST` com um `RunAgentInput` e o servidor devolve uma sequência
tipada — `RUN_STARTED`, `STEP_*`, `TEXT_MESSAGE_*`, `TOOL_CALL_*`,
`STATE_*`, `CUSTOM`, `RUN_FINISHED`/`RUN_ERROR` — cada evento como um objeto
JSON em `data:`. Em Python, o pacote `ag-ui-protocol` traz os tipos Pydantic e
o `EventEncoder`; em JS, `@ag-ui/client` traz um `HttpAgent`.

### O que o brainstorm decidiu

1. **Objetivo: enriquecer a UI do turno.** A pessoa deve ver a linha do tempo
   dos passos (gate → busca → resposta ou recusa) e as tool calls
   (`web_search`, `fetch_notion_page`) enquanto acontecem. Não há cliente
   externo na mira (CopilotKit, Slack, Teams); o frontend próprio continua
   sendo o único consumidor.
2. **Nada de conteúdo bruto de tool na UI.** O que a tool devolve ao modelo
   (página do Notion inteira, resultados da Tavily) é maior do que o que a
   resposta final revela. Pela regra 4 do `CLAUDE.md`, só a resposta filtrada
   chega ao usuário. O `TOOL_CALL_RESULT` carrega apenas um status. O conteúdo
   fica no LangSmith.
3. **Só ao vivo.** Passos e tool calls existem durante o turno e somem no fim.
   Reabrir a conversa mostra texto + fontes, como hoje. Nenhuma migration,
   nenhuma mudança em `messages`. Persistir a linha do tempo por mensagem fica
   como evolução natural — o formato dos eventos já estará definido pelo
   protocolo.
4. **Fontes continuam um bloco único no fim** (evento `CUSTOM`), não estado
   vivo via `STATE_SNAPSHOT/DELTA`. Descartado por escopo.

### Por que não o adaptador pronto

A doc da LangChain (`docs.langchain.com/oss/python/deepagents/ag-ui`) cobre
Deep Agents rodando no LangGraph Platform (`langgraph dev`) com o adaptador
`@ag-ui/langgraph`. O equivalente Python, `ag-ui-langgraph`, dirige o grafo por
conta própria e assume `MessagesState` + checkpointer + `thread_id`. Isso
colide com três decisões deste projeto:

- o grafo **não tem checkpointer** (ADR-0016): histórico vive em
  `conversations`/`messages`;
- `deps` e `signals` são injetados **por request** no `configurable`, e os
  repositórios dentro de `deps` leem a sessão do ContextVar (regra 3);
- o **consumo em duas fases** (`runner.py`) existe para gate e retrieval
  rodarem com a sessão de banco viva, antes do corpo SSE começar; e a
  `AnswerQuestionAction` persiste conversa e mensagem do usuário antes do
  stream, atrás de `require_user`.

Adotar o adaptador significaria desmontar tudo isso. **O protocolo é
implementado por cima do nosso runner**, usando do pacote apenas os tipos e o
encoder.

## Decisão

- `POST /conversations/ask` passa a **receber `RunAgentInput` e responder a
  sequência de eventos AG-UI**, mantendo caminho, `require_user` e a
  persistência pós-stream.
- O `AgentStreamChunk` do `TurnGraphPort` vira uma **união de dataclasses
  puras** que inclui passos e tool calls. Domínio e eval continuam sem
  conhecer `ag_ui`.
- O `runner.py` **deixa de filtrar** os `updates` dos nós e os
  `tool_call_chunks` do nó `answer`, sintetizando os chunks novos. `builder`,
  `nodes` e `edges` não mudam.
- A tradução chunk → evento AG-UI mora em **`src/app/api/streaming/`**, camada
  `app`. O protocolo não entra em `src/domain` nem em `src/support/agent`.
- O frontend consome os eventos com **parser próprio** tipado nos eventos
  AG-UI, sem `@ag-ui/client`. O estado do turno continua no `ChatPage`.
- `threadId` passa a ser **gerado pelo cliente** e vira o id da conversa
  (find-or-create, escopado ao usuário). `runId` também vem do cliente e vira
  o `run_id` do LangSmith.

## Fora de escopo

- `@ag-ui/client` e CopilotKit. Fazem sentido no dia em que houver um cliente
  externo; a entrada conformante desta spec deixa a porta aberta.
- `RunAgentInput.tools`, `context`, `state`, `forwardedProps`, `resume`:
  aceitos e ignorados. Tools de frontend, human-in-the-loop e estado
  compartilhado são outra spec.
- Fontes como `STATE_SNAPSHOT/DELTA`.
- Persistir passos/tool calls por mensagem.
- Eventos `REASONING_*` (o oráculo não expõe raciocínio).
- Tornar gate e retrieval realmente ao vivo (ver "Limitação conhecida").

## 1. Contrato do endpoint

### 1.1 Entrada

`POST /conversations/ask`, `Content-Type: application/json`,
`Accept: text/event-stream`. Body = `RunAgentInput` (camelCase no fio):

```json
{
  "threadId": "<uuid>",
  "runId": "<uuid>",
  "messages": [{ "id": "<uuid>", "role": "user", "content": "como funciona a renovação?" }],
  "tools": [],
  "context": [],
  "forwardedProps": {}
}
```

Regras de interpretação, todas validadas **antes** de abrir o stream (falha é
HTTP 422, nunca evento):

| campo | regra |
|---|---|
| `threadId` | UUID obrigatório. É o id da conversa: existe e é do usuário → continua; não existe → cria com esse id; é de outro usuário → **404** (`ConversationAccessPolicy` nunca revela que a conversa existe, ADR-0017). |
| `runId` | UUID obrigatório. Vira `run_id` do LangSmith e `langsmith_run_id` do trace. |
| `messages[-1]` | `role == "user"` e conteúdo não vazio. É a pergunta. O restante do histórico do cliente é ignorado: a recência continua vindo do Postgres por orçamento de tokens. |
| `tools`, `context`, `state`, `forwardedProps`, `resume`, `parentRunId` | aceitos e ignorados. |

O `RunAgentInput` exige `tools`, `context` e `forwardedProps` presentes; o
cliente manda vazios.

### 1.2 Saída

`200`, `text/event-stream`, cada evento como `data: {json}\n\n` (sem campo
`event:`). Há **um único `messageId` de assistente por run**, gerado pelo
servidor (UUID v7). Ordem:

| momento | evento |
|---|---|
| abertura do corpo | `RUN_STARTED {threadId, runId}` |
| nó gate / retrieve / refuse / answer | `STEP_STARTED {stepName}` … `STEP_FINISHED {stepName}` |
| detalhe de passo com dado útil | `CUSTOM {name: "oracle.step", value: {step, …}}` imediatamente após o `STEP_FINISHED` |
| modelo pede tool | `TOOL_CALL_START {toolCallId, toolCallName, parentMessageId}` → `TOOL_CALL_ARGS {toolCallId, delta}` (fragmentos do JSON dos argumentos) → `TOOL_CALL_END {toolCallId}`. `TOOL_CALL_ARGS` só sai para tools cujos argumentos são exibíveis (`web_search`); `fetch_notion_page` nunca emite `ARGS` — o `page_id` não cruza o port (regra 4). |
| tool devolveu | `TOOL_CALL_RESULT {messageId, toolCallId, content}` com `content` = `{"status":"ok"}` ou `{"status":"error"}`. **Nunca o conteúdo da tool.** |
| primeiro texto | `TEXT_MESSAGE_START {messageId, role: "assistant"}` |
| cada token | `TEXT_MESSAGE_CONTENT {messageId, delta}` |
| texto encerrado | `TEXT_MESSAGE_END {messageId}` |
| fontes | `CUSTOM {name: "oracle.sources", value: {citations: [...]}}` |
| fim | `RUN_FINISHED {threadId, runId}` |
| falha durante o stream | `RUN_ERROR {message}` genérico e fim do stream. **Sem `RUN_FINISHED` depois.** |

Detalhes do `oracle.step`:

| step | value |
|---|---|
| `gate` | `{step: "gate", retrieve: bool, degraded: bool}` |
| `retrieve` | `{step: "retrieve", kept: int}` |
| `refuse` | sem `CUSTOM` |
| `answer` | sem `CUSTOM` |

Regras de passos:

- `answer` abre **uma vez** (primeira entrada no nó) e fecha **uma vez** (fim
  do stream), mesmo com tool loop no meio. Re-entradas `answer → tools →
  answer` não geram passos novos.
- O nó `tools` **não vira passo**: as tool calls já contam a história.
- Recusa emite `STEP refuse` e depois `TEXT_MESSAGE_*` com o texto canônico,
  igual a qualquer resposta. `citations` vem vazio.
- Com `preset_knowledge` (eval adversarial) não há gate nem retrieve; só
  `answer`.

`TEXT_MESSAGE_START` só é emitido quando há texto. Um run que morre antes do
primeiro token emite `RUN_STARTED`, os passos que houve e `RUN_ERROR`.

## 2. Ports: o `AgentStreamChunk` vira união

`src/support/agent/ports.py` troca o dataclass único com `type: Literal["text",
"sources"]` por uma união de dataclasses puras, sem `ag_ui`:

```python
@dataclass
class TextChunk:
    text: str

@dataclass
class SourcesChunk:
    citations: list[Citation]

@dataclass
class StepChunk:
    name: str                       # "gate" | "retrieve" | "refuse" | "answer"
    phase: Literal["started", "finished"]
    detail: dict | None = None      # só em finished, quando houver

@dataclass
class ToolCallStartChunk:
    id: str
    name: str

@dataclass
class ToolCallArgsChunk:
    id: str
    delta: str

@dataclass
class ToolCallEndChunk:
    id: str

@dataclass
class ToolCallResultChunk:
    id: str
    status: Literal["ok", "error"]

AgentStreamChunk = (
    TextChunk | SourcesChunk | StepChunk
    | ToolCallStartChunk | ToolCallArgsChunk | ToolCallEndChunk | ToolCallResultChunk
)
```

Consumidores distinguem por `isinstance`, não mais por `chunk.type`. O teste
de fronteira `tests/unit/support/agent/test_domain_boundary.py` continua
valendo e ganha uma regra: `src/domain` e `src/support/agent` não importam
`ag_ui`.

`evals/runner.py` (consome `chunk.type == "text"`) passa a `isinstance(chunk,
TextChunk)` e ignora os chunks novos. Nada mais muda no eval.

## 3. Runner: abrir o filtro sem tocar no grafo

Três mudanças em `src/support/agent/graph/runner.py`. `builder.py`, `nodes.py`
e `edges.py` **não mudam**. Os modos de stream continuam `["updates",
"messages"]`.

### 3.1 `updates` viram passos, tool ends e tool results

Cada update de nó (`gate`, `retrieve`, `refuse`, `answer`) produz:

1. `StepChunk(name, "started")` **se ainda não foi emitido** para esse nome
   (sintetizado: `updates` só chega no fim do nó);
2. `StepChunk(name, "finished", detail)` com `detail` lido dos `signals`
   (`gate_retrieve`/`gate_degraded`, `retrieval_kept`) — exceto `answer`, cujo
   `finished` só sai no fim do stream (ver 3.3).

Update de `answer` cuja última `AIMessage` tem `tool_calls` fecha os
`ToolCallEndChunk` ainda pendentes (ids vistos no `messages` sem `end`).

Update de `tools` produz um `ToolCallResultChunk` por `ToolMessage`, com
`status = "error"` quando o conteúdo (já sem o envelope `<<TOOL_CONTENT>>`)
começa com `(falha` — é o formato que `tools.py` usa para falha capturada —
e `"ok"` caso contrário.

A absorção de `citations` (`_absorb`) e a síntese da recusa (`_refusal_chunk`)
continuam iguais.

### 3.2 `messages` deixa de descartar chunks sem texto

Hoje `_token_chunk` devolve `None` para `AIMessageChunk` sem texto, o que
descarta os `tool_call_chunks`. Passa a:

- `tool_call_chunks` com `id` e `name` → `ToolCallStartChunk` (uma vez por id,
  controlado por um conjunto de ids vistos);
- `tool_call_chunks` com `args` → `ToolCallArgsChunk(id, delta)`. Anthropic e
  OpenAI mandam o `id` no primeiro fragmento e `index` nos seguintes; o runner
  resolve `index → id` com um mapa por run.
- `AIMessage` inteira com `tool_calls` (provedor sem streaming de tool call,
  ou fake de teste) → `start`, `args` com o JSON completo e `end` de uma vez.

Texto continua exigindo `langgraph_node == "answer"` e tipo `AIMessage`/
`AIMessageChunk`. `ToolMessage` nunca vira texto.

### 3.3 Fase 1 acumula; fase 2 reproduz

`start()` deixa de guardar um único `first` e acumula `buffered:
list[AgentStreamChunk]` com tudo que a fase 1 produziu (passos de gate e
retrieve, o passo `refuse` ou o `answer started`, o primeiro token se houver).
`_resume` reproduz a lista antes de continuar consumindo o gerador. O
critério de corte da fase 1 **não muda**: primeiro evento `messages` do nó
`answer`, ou update do `refuse`. O tratamento de exceção adiada (revisão I3 do
ADR-0016) também não muda.

No fim do stream, `_resume` emite `StepChunk("answer", "finished")` se o
`answer` foi aberto, depois `SourcesChunk`.

## 4. `AnswerQuestionAction`: find-or-create por id

`execute(question, conversation_id: UUID, user_email)` — o id passa a ser
obrigatório e vem do `threadId`:

- `get_by_id` encontra → `ConversationAccessPolicy.assert_can_access` (404 se
  for de outro usuário — a policy nunca revela que a conversa existe), continua;
- não encontra → `create` com `uuid=conversation_id`, título = pergunta
  truncada, como hoje.

O `NotFoundError` deixa de existir nesse caminho. Nada mais muda na Action; o
`TurnTraceDraft.langsmith_run_id` continua sendo preenchido pelo controller,
agora com o `runId` do cliente.

## 5. Camada `app`: request, encoder, controller

### 5.1 `src/app/api/requests/run_agent_request.py`

Reexporta `RunAgentInput` de `ag_ui.core` e concentra os validadores da seção
1.1 (UUIDs, última mensagem). Regra 7 preservada: schema Pydantic mora em
`src/app/api/`.

### 5.2 `src/app/api/streaming/ag_ui_encoder.py`

Função pura `to_events(chunk, ctx) -> list[BaseEvent]` + um pequeno objeto de
contexto do run (`thread_id`, `run_id`, `message_id`, flag `text_started`).
Responsável por:

- abrir `TEXT_MESSAGE_START` no primeiro `TextChunk` e fechar
  `TEXT_MESSAGE_END` antes de `oracle.sources`;
- `StepChunk` → `STEP_STARTED`/`STEP_FINISHED` (+ `CUSTOM oracle.step` quando
  `detail` não é `None`);
- `ToolCall*Chunk` → `TOOL_CALL_*`, com `parentMessageId = message_id` e
  `messageId` do result = UUID novo por result;
- `SourcesChunk` → `CUSTOM oracle.sources` com o payload de citação atual
  (`source_type`, `title`, `url`, `snippet`).

Serialização via `EventEncoder.encode()`. Testável sem HTTP.

### 5.3 Controller

`ConversationController.ask(data: RunAgentRequest)`:

1. valida (422 automático via Pydantic);
2. `run_id = data.run_id`; monta `AnswerQuestionAction` como hoje, com
   `get_turn_graph_runner(run_id=..., user_hash=...)`;
3. `await action.execute(question, thread_id, user_email)` — fase 1, sessão
   viva;
4. corpo SSE: `RUN_STARTED`, depois `for chunk in stream: for ev in
   to_events(chunk, ctx): yield encoder.encode(ev)`, capturando texto e
   citações para persistir; `except` → `RUN_ERROR` e `draft.outcome = "error"`;
   `_absorb_engine_metrics` + `_persist_turn` inalterados; `RUN_FINISHED` só se
   não falhou.

`_sse()` e `_citation_payload()` saem do controller para o encoder.
`media_type = encoder.get_content_type()`.

## 6. Frontend

### 6.1 API

- `lib/api/sse.ts`: lê só `data:`, ignora `event:`, `id:`, `retry:`.
- `lib/api/agui.ts` (novo): tipos TypeScript dos eventos consumidos (união
  discriminada por `type`, camelCase) e `parseAgUiStream(body)` que faz
  `JSON.parse` de cada `data:` e **descarta** linha malformada ou `type`
  desconhecido — tolerância a eventos futuros do protocolo.
- `lib/api/conversations.ts` → `askStream(input)`: monta o `RunAgentInput`
  (`threadId = input.conversationId ?? crypto.randomUUID()`, `runId =
  crypto.randomUUID()`, uma mensagem `user` com id próprio, `tools`/`context`/
  `forwardedProps` vazios) e traduz os eventos AG-UI para o `AskEvent`
  interno. O hook e seus testes não conhecem o protocolo.

`AskEvent` estendido (`lib/types.ts`):

```ts
type AskEvent =
  | { type: "run_started"; conversationId: string }
  | { type: "step"; name: string; phase: "started" | "finished"; detail?: Record<string, unknown> }
  | { type: "tool_call_start"; id: string; name: string }
  | { type: "tool_call_args"; id: string; delta: string }
  | { type: "tool_call_end"; id: string }
  | { type: "tool_call_result"; id: string; status: "ok" | "error" }
  | { type: "token"; text: string }
  | { type: "sources"; citations: Citation[] }
  | { type: "error"; message: string }
  | { type: "done" };
```

`STEP_FINISHED` seguido de `CUSTOM oracle.step` é fundido num único
`step finished` com `detail` — o tradutor segura o `finished` até o próximo
evento e o libera com ou sem detalhe.

### 6.2 Hook

`useAskStream` mantém `status`, `answer`, `citations`, `conversationId`,
`errorMessage` e ganha `activity: ActivityItem[]`, lista única em ordem de
chegada:

```ts
type ActivityItem =
  | { kind: "step"; name: string; status: "running" | "done"; detail?: Record<string, unknown> }
  | { kind: "tool"; id: string; name: string; argsRaw: string; args?: Record<string, unknown>;
      status: "pending" | "running" | "ok" | "error" };
```

- `tool_call_start` → item `pending`; `args` acumula `argsRaw`; `end` parseia
  `args` e marca `running`; `result` marca `ok`/`error`.
- `conversationId` é definido no `run_started`, antes do primeiro token.
- Stream que termina sem `done` nem `error` → `status = "error"`,
  `errorMessage = "conexão interrompida"`. Corrige o estado preso em
  `streaming` que existe hoje.

### 6.3 UI

`TurnTimeline` (novo, em `features/chat/components/`) substitui o
`ThinkingIndicator` no mesmo ponto do layout e recebe `activity`. Cada item:
ícone de estado (girando / concluído / falhou), rótulo em português, detalhe
quando houver. Rótulos em `features/chat/timelineLabels.ts`:

| item | rótulo |
|---|---|
| `gate` | Entendendo a pergunta |
| `retrieve` | Buscando na base · N trechos |
| `refuse` | Nada na base cobre essa pergunta |
| `answer` | Respondendo |
| `web_search` | Buscando na web: «query» |
| `fetch_notion_page` | Lendo página do Notion |

`fetch_notion_page` não mostra o `page_id`. A linha do tempo aparece do
`run_started` até `done`/`error` e então desmonta. `prefers-reduced-motion`
desliga a animação do ícone. `ChatPage` mantém a estrutura; a adoção do id da
conversa nova continua no mesmo efeito, só que o id chega mais cedo.

## 7. Falhas

| onde | o que acontece |
|---|---|
| body inválido | 422, sem stream |
| sem cookie | 401, sem stream; frontend já trata (`handleUnauthorized`) |
| `threadId` de outro usuário | 404, sem stream (ADR-0017: não revelar que existe) |
| gate/retrieval quebram (fase 1) | 500, sem stream; rollback do `DBSessionMiddleware` (inalterado, ADR-0016) |
| estágio de resposta quebra (fase 2) | `RUN_ERROR` genérico; trace com `outcome=error`; resposta não persistida (inalterado) |
| tool falha | **não é erro do run**: `TOOL_CALL_RESULT status=error`, o modelo segue respondendo (inalterado no backend) |
| stream cortado sem `RUN_FINISHED` | frontend vai para `error` "conexão interrompida" |
| evento malformado / tipo desconhecido | frontend ignora a linha |

Retry no frontend reusa o `threadId` e gera `runId` novo — é o que o
protocolo espera. Como hoje, retry grava outra mensagem de usuário.

## 8. Limitação conhecida

Por causa do consumo em duas fases, o corpo SSE só começa **depois** que gate
e retrieval terminaram. `RUN_STARTED` e os passos `gate` e `retrieve` chegam ao
navegador numa rajada junto com o primeiro token (ou com o `refuse`). A linha
do tempo mostra a sequência correta, mas os dois primeiros passos não
"acendem" um a um em tempo real; até o corpo começar, a UI mostra o mesmo
estado de espera de hoje.

Tornar isso realmente ao vivo exigiria mover a fase 1 para dentro do corpo
SSE com sessão própria (`run_in_async_session`), o que altera a invariante da
seção 5 do ADR-0016 e o tratamento de falha da fase 1 (rollback da mensagem do
usuário). **Não faz parte desta spec.** Fica registrado como evolução.

## 9. Dependências

- Backend: `ag-ui-protocol>=0.1,<1` (verificado 0.1.22; depende só de
  `pydantic>=2.11.2`). Discutido e aprovado no brainstorm (regra 10).
- Frontend: nenhuma. `crypto.randomUUID()` é nativo.

## 10. Testes

Backend:

- `tests/unit/support/agent/graph/test_runner.py`: grafo fake que emite
  `updates` e `messages` com `tool_call_chunks` e `ToolMessage`; asserta a
  sequência de chunks (passos na ordem, tool start/args/end/result, texto,
  fontes). Casos: `AIMessage` inteira com `tool_calls` sem streaming;
  recusa; `preset_knowledge`; `answer finished` uma só vez com tool loop.
- `tests/unit/app/api/streaming/test_ag_ui_encoder.py` (novo): um único
  `TEXT_MESSAGE_START`, antes do primeiro delta; `TEXT_MESSAGE_END` antes de
  `oracle.sources`; mesmo `messageId` em todo o run; `parentMessageId` das
  tool calls = `messageId`; `oracle.step` só quando há detalhe; run sem texto
  não emite `TEXT_MESSAGE_*`.
- `tests/unit/app/api/requests/test_run_agent_request.py` (novo): UUID
  inválido, última mensagem não é `user`, conteúdo vazio → 422.
- `tests/integration/api/test_ask_endpoint.py` e
  `test_ask_trace_persistence.py`: body `RunAgentInput`, parse de `data:`;
  casos novos: find-or-create por `threadId`, 404 para thread alheia,
  `langsmith_run_id == runId`, `RUN_ERROR` persiste trace e não persiste
  resposta, `RUN_FINISHED` ausente após `RUN_ERROR`.
- `tests/unit/support/agent/test_domain_boundary.py`: `src/domain` e
  `src/support/agent` não importam `ag_ui`.
- `tests/unit/evals/test_runner.py`: continua verde com `isinstance`.

Frontend:

- `lib/api/agui.test.ts` (novo): linha malformada, tipo desconhecido,
  camelCase → `AskEvent`; fusão `STEP_FINISHED` + `oracle.step`.
- `hooks/useAskStream.test.ts`: `activity` (ordem, estados de tool call,
  parse de args no `end`), `conversationId` no `run_started`, stream cortado
  → `error`.
- `features/chat/components/TurnTimeline.test.tsx` (novo): rótulos, detalhe
  de `retrieve`, `page_id` não aparece, desmonta em `done`.
- `features/ops/architectureMap.test.ts`: segue passando com os arquivos
  novos declarados.

## 11. Sequência de corte

1. **ADR-0019** (substitui o 0009): contrato de eventos AG-UI do turno.
   Atualizar `docs/adr/README.md` e o `CLAUDE.md` (stack + lista de ADRs).
2. Dependência `ag-ui-protocol` no `pyproject.toml` + lock.
3. `ports.py`: união de chunks; ajustar `evals/runner.py` e o teste de
   fronteira.
4. `runner.py`: 3.1 → 3.2 → 3.3, com os testes unitários.
5. `AnswerQuestionAction`: find-or-create.
6. `requests/run_agent_request.py` + `streaming/ag_ui_encoder.py` + controller,
   com os testes de integração.
7. `architectureMap.ts` **no mesmo commit** do item 6: caixa "Pergunta" passa a
   dizer "POST /conversations/ask, `RunAgentInput` → eventos AG-UI" e declara
   `src/app/api/streaming/ag_ui_encoder.py` e
   `src/app/api/requests/run_agent_request.py`.
8. Frontend: `sse.ts` → `agui.ts` → `conversations.ts` → `useAskStream` →
   `TurnTimeline` + `timelineLabels.ts` → `ChatPage`.
9. `docs/architecture.md` (fluxo do turno) e `docs/adr/0016` não mudam; a
   spec do LangGraph de 2026-09-01 ganha uma nota apontando para esta.

Backend e frontend mudam o contrato ao mesmo tempo: não há período em que o
servidor fale AG-UI e o cliente fale o contrato antigo. Deploy conjunto.

## 12. Critérios de aceite

- Uma pergunta substantiva mostra, nesta ordem: "Entendendo a pergunta" →
  "Buscando na base · N trechos" → "Respondendo" → texto em streaming →
  fontes. A linha do tempo desaparece ao terminar.
- Uma pergunta que dispara `web_search` mostra "Buscando na web: «query»"
  entre dois momentos de "Respondendo", com estado concluído ou falhou.
- Uma recusa mostra "Entendendo a pergunta" → "Buscando na base · 0 trechos"
  → "Nada na base cobre essa pergunta" → texto canônico, sem fontes.
- Nenhum evento carrega conteúdo de tool, `page_id`, e-mail ou
  `<<TOOL_CONTENT>>`.
- `curl` com `RunAgentInput` válido devolve `data:` JSON conforme a seção 1.2;
  body inválido devolve 422; `threadId` alheio devolve 404.
- Reabrir a conversa mostra texto + fontes; `agent_traces.langsmith_run_id`
  bate com o `runId` enviado.
- `pytest`, `npm test`, `alembic check` e `prospector` verdes; nenhuma
  migration nova.
