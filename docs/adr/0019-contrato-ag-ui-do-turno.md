# ADR-0019 — O turno do oráculo é entregue como eventos AG-UI

## Status

Aceito — 2026-09-04. Substitui o [ADR-0009](0009-streaming-sse.md) (contrato de
eventos do chat). O transporte SSE do 0009 permanece; muda o que trafega nele.

## Resumo

- **Decisão:** `POST /conversations/ask` recebe um `RunAgentInput` do protocolo
  **AG-UI** (Agent–User Interaction Protocol) e responde, sobre SSE, a sequência
  de eventos do protocolo: `RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`,
  `TEXT_MESSAGE_*`, `CUSTOM` (`oracle.step`, `oracle.sources`), `RUN_FINISHED`
  ou `RUN_ERROR`. A tradução dos chunks do grafo para esses eventos mora em
  `src/app/api/streaming/` (camada `app`), usando do pacote `ag-ui-protocol`
  apenas os tipos e o `EventEncoder`. `threadId` (= id da conversa) e `runId`
  (= run do LangSmith) são gerados pelo cliente.
- **Aplica-se quando:** for mexer no endpoint do chat, no que o frontend recebe
  durante um turno, no `AgentStreamChunk` do `TurnGraphPort`, ou for ligar
  outro cliente ao oráculo.
- **Regra prática:** o protocolo não entra em `src/domain/` nem em
  `src/support/agent/` (teste de fronteira). `TOOL_CALL_RESULT` carrega só
  `{"status": ...}` — nunca o conteúdo da tool (regra 4). Nada da linha do
  tempo é persistido: `messages` continua guardando só texto + fontes.

---

## Contexto

O ADR-0009 definiu um contrato SSE caseiro com cinco eventos (`conversation`,
`token`, `sources`, `error`, `done`). Ele bastava para "texto + fontes", mas
esconde tudo o que o grafo (ADR-0016) faz entre a pergunta e o primeiro token:
gate, retrieval, recusa e tool calls. Queremos mostrar isso na UI como linha do
tempo do turno, sem inventar mais um vocabulário próprio.

O AG-UI é um protocolo aberto exatamente para isso — eventos tipados de agente
para interface, sobre HTTP + SSE — com SDKs em Python e JS e adaptadores para
LangGraph, CrewAI, Pydantic AI etc.

## Decisão

1. **Entrada** é o `RunAgentInput` do protocolo. `threadId` é o id da conversa
   (UUID gerado pelo cliente; find-or-create escopado ao usuário; thread de outro
   usuário é 404 pela `ConversationAccessPolicy`). `runId` vira o `run_id` do
   LangSmith e o `langsmith_run_id` do trace. A pergunta é a última mensagem
   `user`; o restante do histórico do cliente é ignorado — a recência continua
   vindo do Postgres por orçamento de tokens. `tools`, `context`, `state`,
   `forwardedProps`, `resume` são aceitos e ignorados.
2. **Saída** segue o protocolo. Um `messageId` de assistente por run. Passos do
   grafo (`gate`, `retrieve`, `refuse`, `answer`) viram `STEP_STARTED/FINISHED`;
   detalhe útil (`retrieve`/`degraded` do gate, `kept` do retrieval) vai num
   `CUSTOM oracle.step`. Tool calls viram `TOOL_CALL_START/ARGS/END/RESULT`, com
   o result carregando só um status. Fontes vão num `CUSTOM oracle.sources` no
   fim. Falha no meio do stream é `RUN_ERROR` e encerra o stream sem
   `RUN_FINISHED`.
3. **Onde mora.** O `AgentStreamChunk` do port vira uma união de dataclasses
   puras (texto, fontes, passo, tool call start/args/end/result). O runner
   sintetiza esses chunks a partir dos `updates` e `messages` do LangGraph. A
   tradução para eventos AG-UI é da camada `app` (`src/app/api/streaming/`).
   Domínio, grafo e eval não conhecem `ag_ui`.
4. **Sem o adaptador pronto.** `ag-ui-langgraph` dirige o grafo por conta
   própria e assume checkpointer + `MessagesState`; isso colide com "sem
   checkpointer" (ADR-0016), com as dependências injetadas por request e com o
   consumo em duas fases. O protocolo é implementado por cima do nosso runner.
5. **Frontend com parser próprio.** Sem `@ag-ui/client`/CopilotKit enquanto não
   houver cliente externo; o estado do turno continua no `ChatPage`.

## Consequências

**Positivas**
- A UI mostra a linha do tempo do turno e as tool calls com vocabulário padrão.
- O endpoint é AG-UI de ponta a ponta: qualquer cliente do protocolo pluga sem
  código sob medida no servidor.
- `runId` do cliente = run do LangSmith: um turno da tela liga ao trace sem
  intermediário.

**Negativas / riscos**
- Por causa do consumo em duas fases, `RUN_STARTED` e os passos `gate` e
  `retrieve` chegam numa rajada com o primeiro token. A sequência está certa;
  os dois primeiros passos não "acendem" um a um. Tornar isso ao vivo exige
  mover a fase 1 para dentro do corpo SSE — fora deste ADR.
- O `RunAgentInput` exige `tools`, `context` e `forwardedProps` presentes; o
  cliente manda vazios.
- Deploy conjunto de backend e frontend: não há período de coexistência com o
  contrato do 0009.

## Alternativas consideradas

- **Manter o contrato caseiro e só acrescentar eventos** — rejeitado: mais um
  vocabulário próprio para manter, sem interoperabilidade.
- **`ag-ui-langgraph`** — rejeitado (item 4 acima).
- **`@ag-ui/client` / CopilotKit no frontend** — adiado: duplicaria o estado
  que o `ChatPage` já gerencia e traz RxJS; faz sentido só com cliente externo.
- **Fontes como `STATE_SNAPSHOT/DELTA`** — adiado por escopo; o bloco único no
  fim continua.
