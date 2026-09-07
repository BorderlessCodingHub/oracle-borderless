# ADR-0021 — O turno é entregue como `StreamEvent` do `astream_events`

## Status

Aceito — 2026-09-07. Substitui o **contrato** do ADR-0019 (eventos AG-UI). Mantém o transporte SSE (ADR-0009), a regra 4 e o consumo em duas fases no corpo SSE (ADR-0020).

## Resumo

- **Decisão:** `POST /conversations/ask` recebe `{"input": {"question"}, "config": {"run_id", "configurable": {"thread_id"}}}` — os parâmetros de `astream_events(input, config)` — e responde, sobre SSE, blocos `event: <nome>\ndata: <StreamEvent JSON>` produzidos por `graph.astream_events(version="v2", stream_mode=["values", "updates"])`. O runner aplica uma **allowlist de eventos** e uma **projeção fixa** sobre `data` antes de qualquer evento cruzar o port (`GraphEvent`, espelho do `StreamEvent`). A camada `app` só serializa e sintetiza um único evento próprio, `on_chain_error`.
- **Aplica-se quando:** for mexer no endpoint do chat, no que o frontend recebe durante um turno, no `TurnGraphPort`, no runner, ou for ligar outro cliente ao oráculo.
- **Regra prática:** nada sai do runner fora da allowlist (raiz: `on_chain_start/stream/end`; nós `gate`/`retrieve`/`refuse`/`answer`: `on_chain_start/end`; `on_chat_model_stream` só do `answer`; `on_tool_start/end/error`). `data.input` de nó e de modelo nunca sai. `knowledge` vira `kept`; `messages`, `question`, `history`, `search_query` caem; `on_tool_end` carrega só `{status, tool_call_id}`; `on_tool_start` carrega `input` só para `web_search`. `metadata` passa por allowlist (`langgraph_node`, `langgraph_step`, `thread_id`, `ls_provider`, `ls_model_name`). O corte da fase 1 é o `on_chain_start` do `answer` ou o `on_chain_end` do `refuse`. `answer` abre e fecha uma vez.

---

## Contexto

O ADR-0019 pôs o AG-UI no fio: o runner consumia `astream(stream_mode=["updates", "messages", "debug"])`, um `TurnEmitter` sintetizava sete dataclasses de chunk e um encoder na camada `app` os traduzia em `RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`, `TEXT_MESSAGE_*`, `CUSTOM`, `RUN_FINISHED`/`RUN_ERROR`. Funcionava, mas eram dois vocabulários (chunks do port e eventos do protocolo) para contar a mesma história, mais um terceiro no frontend.

O LangChain já tem um formato de evento de streaming, o `StreamEvent` (`langchain_core.runnables.schema`), produzido por `Runnable.astream_events`. Um `CompiledStateGraph` aceita `stream_mode` nessa chamada; os chunks de cada modo chegam como `on_chain_stream` do grafo raiz. A entrada de cada nó é um `on_chain_start` com `metadata.langgraph_node` — exatamente o sinal que o modo `debug` fornecia para o corte da fase 1.

O evento cru, porém, carrega o state inteiro (`data.input` de cada nó, snapshots de `values`), o prompt completo (`on_chat_model_start`) e a `ToolMessage` inteira (`on_tool_end`). Mandar isso ao cliente viola a regra 4. Os filtros nativos (`include_*`/`exclude_*`) operam por nome/tipo/tag e não tocam em `data`, então não bastam.

## Decisão

1. **Fio = `StreamEvent`.** Cada bloco SSE é `event: <data.event>\ndata: <JSON com os sete campos>`.
2. **`astream_events(version="v2", stream_mode=["values", "updates"])`.** Sem `custom`, sem `messages`, sem `debug`. Os dois modos saem no fio; o frontend consome `updates` e os eventos de nó/modelo/tool; `values` vai por fidelidade ao método.
3. **Redação no runner.** `EventRedactor.redact(raw) -> GraphEvent | None` aplica a allowlist e a projeção (spec 07/09, §1.2). O port fala `GraphEvent` (dataclass puro, sem `langchain`); `text_of(event)` e `citations_of(event)` extraem o que o controller persiste.
4. **Corte da fase 1:** `on_chain_start` do nó `answer` (primeira entrada; re-entradas do tool loop são descartadas) ou `on_chain_end` do nó `refuse`. O `on_chain_end` do `answer` é segurado e emitido antes do `on_chain_end` do raiz — é o evento real da última saída do nó, atrasado, não um evento inventado.
5. **Camada `app`:** `StreamEventsRequest` (`{input, config}`), `stream_event_encoder.encode()` e `error_event()` (`on_chain_error`, terminal, sem `on_chain_end` depois). O `on_chain_end` do raiz é retido pelo controller e emitido só depois de persistir o turno.
6. **Frontend:** `sse.ts` lê `event:`; `streamEvents.ts` valida o `StreamEvent` e traduz para o `AskEvent` de sempre. Hook e UI não mudam.
7. **`ag-ui-protocol` removido** do `pyproject.toml` (regra 10: remoção registrada aqui).

## Consequências

**Positivas**
- Um vocabulário só, do grafo ao navegador; qualquer cliente LangChain-aware lê o fio sem adaptador.
- O `debug` sai: a entrada do nó vem do evento padrão `on_chain_start`.
- A redação fica num ponto único e testável (teste percorre `data` recursivamente procurando chaves proibidas).

**Negativas / riscos**
- `values` duplica o state projetado a cada super-step — custo pequeno porque a projeção é minúscula, mas existe.
- Tokens dependem de o modelo stremar dentro de `astream_events` (`BaseChatModel._should_stream` detecta o handler). Anthropic e OpenAI stremam; um modelo que não strema não produz `on_chat_model_stream` e o texto não chega ao fio — fakes de teste precisam ser `BaseChatModel` de verdade.
- `on_chain_error` é um nome nosso (o `astream_events` não emite erro como evento; ele levanta). Segue a convenção `on_<tipo>_<fase>` para não criar um segundo estilo.

## Alternativas consideradas

- **Manter AG-UI e só trocar `astream` por `astream_events` por baixo** — mantinha os três vocabulários; não era o pedido.
- **Mandar o evento cru** — viola a regra 4 (state, prompt, conteúdo de tool). Rejeitada.
- **Filtrar com `include_*`/`exclude_*` nativos** — não expressam "só `on_chat_model_stream` do nó `answer`" nem tocam em `data`. Rejeitada; a allowlist mora inteira no redator.
- **`version="v3"`** — beta, protocolo por blocos de conteúdo. Fora até estabilizar.
- **Manter `RunAgentInput` como body** — mantinha `ag_ui` só pelo schema de entrada. Rejeitada: o body espelha `astream_events(input, config)`.
