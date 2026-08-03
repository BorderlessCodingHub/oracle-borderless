# Design — Página de Ops: trace por turno + mapa vivo da arquitetura

**Data:** 2026-08-03
**Status:** aprovado (brainstorming) — aguardando plano de implementação
**ADR novo:** ADR-0013 — Trace por turno persistido no Postgres, coletado num ponto único
**Relacionados:** [ADR-0007](../../adr/0007-agent-framework-pydantic-ai.md) (Pydantic AI), [ADR-0009](../../adr/0009-streaming-sse.md) (SSE), [ADR-0012](../../adr/0012-escopo-kb-aplicado-na-recuperacao.md) (escopo na recuperação), [judge eval](2026-07-22-judge-eval-design.md), [retrieval gate](2026-07-22-retrieval-gate-design.md)
**Inspiração:** `waku-agent-guide.md` §4 (Eval/LLM-Ops) e §5 (as três camadas de visualização)

## Problema

Um turno do oráculo hoje passa por **três decisões em série** e não deixa rastro de nenhuma:

1. o **gate** decide `skip` ou `retrieve`, e reescreve a query ([retrieval_gate.py](../../../src/support/agent/retrieval_gate.py));
2. o **limiar** de distância decide o que vira contexto ([document_chunk_repository.py](../../../src/domain/documents/repositories/document_chunk_repository.py));
3. o **prompt** decide entre responder e emitir a recusa padrão ([prompts.py](../../../src/support/agent/prompts.py)).

Quando uma resposta sai errada, não há como saber qual das três falhou. O que existe hoje de observável é o `logging` de erro — nada sobre decisão, latência ou quantos chunks passaram. O pilar 4 do modelo Waku (trace → eval → gate → release) está pela metade: o judge eval existe em [`evals/`](../../../evals/), mas o **trace**, que é o pré-requisito dele, não.

Some-se a isso que a arquitetura só é legível hoje lendo código ou `docs/architecture.md` — não há como *ver* o pipeline com números reais.

## Decisões (do brainstorming)

1. **O objetivo é ver um turno acontecendo**, não só desenhar caixas. Logo o entregável central é o **event stream do turno**; a tela é a consequência.
2. **Trace persistido no Postgres**, não em JSONL. O Waku usa arquivo porque roda local, num processo. Aqui o filesystem do container é efêmero e não é compartilhado entre réplicas — trace em arquivo desapareceria a cada deploy.
3. **Post-hoc, não ao vivo.** A página lista turnos concluídos e abre o detalhe de um. Acender ao vivo exigiria broker em processo, e com mais de uma réplica cada aba veria só os turnos do seu worker.
4. **Mapa desenhado à mão em React + CSS** (não Mermaid), porque o controle visual é o ponto — com o requisito do "mapa honesto" abaixo compensando o risco.
5. **A página fica aberta agora**, com o encaixe da auth de admin pronto num ponto de cada lado. Quando a auth existir, quem não for admin **não renderiza a página nem o link** — recebe 404, não "acesso negado".
6. **O painel de eval lê os reports existentes**; a página nunca dispara eval (é chamada de modelo de verdade, feita no release).

## Requisito: o mapa não pode mentir

Um diagrama mantido à mão envelhece em silêncio. Três amarras, todas obrigatórias:

- **Registro único.** Toda caixa do mapa é declarada em um só lugar — `frontend/src/features/ops/architectureMap.ts` — com `id`, rótulo, descrição e **o caminho do arquivo que a implementa**. A tela renderiza a partir desse registro; nenhuma caixa é escrita solta no JSX.
- **Teste que quebra o build.** Um teste percorre o registro e falha se qualquer caminho declarado não existir mais no repositório. Renomear ou remover um módulo do pipeline sem atualizar o mapa fica vermelho.
- **Regra escrita.** Uma linha no `CLAUDE.md` (seção de mudanças estruturais) e um aviso no topo do registro: mudou o pipeline, muda o mapa no mesmo commit.

A ideia vem do guia do Waku §5.3: *"um diagrama sem correspondência explícita com arquivos apodrece"*. A diferença é que aqui a correspondência é verificada por teste, não confiada à disciplina.

## Desenho

### 1. Coleta do trace

O turno atravessa duas fronteiras de sessão de banco, e isso define onde cada número é medido:

| Fase | Onde acontece | Sessão de banco | Quem mede |
|---|---|---|---|
| recência, gate, retrieval, recusa | `AnswerQuestionAction.execute` | viva (request) | a própria Action |
| engine (tokens do LLM) | gerador SSE do controller | **fechada** | o controller |
| gravação | background task pós-stream | própria (`run_in_async_session`) | a mesma task que já grava o assistente |

`TurnTraceDraft` — dataclass pura em `src/domain/observability/dtos/`, sem I/O — acumula os eventos com o instante relativo de cada um. A Action o cria, preenche as fases que conhece e o devolve junto do stream:

```
execute(...) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]
```

O controller completa a fase do engine (primeiro token, duração, citações, erro) e, na **mesma** `run_in_async_session` que já persiste a resposta, chama `RecordTurnTraceAction`. Uma sessão, duas escritas.

**Tokens e tool calls** só o engine conhece. `OracleEngine.stream_answer` recebe um parâmetro aditivo opcional (`metrics: TurnMetrics | None = None`) que ele preenche — mesmo padrão do `enable_tools=True` que o judge eval já usa, e **sem tocar no contrato SSE** nem nos Protocols de `ports.py` além da assinatura opcional. Os contadores de tool call são incrementados dentro dos closures das tools, que já são nossos.

> **Incerteza registrada:** capturar tokens depende do que o `usage()` do pydantic-ai expõe no caminho `run_stream`. Confirmar na implementação. Se não vier de graça, a v1 grava duração, citações e tool calls, e token/custo vira follow-up explícito — melhor do que uma coluna que nunca preenche.

### 2. Invariantes

- **Trace nunca derruba um turno.** Toda a coleta e a gravação ficam sob `try/except` que loga e engole, no espírito do fail-open do gate. Uma falha de observabilidade não pode custar uma resposta ao usuário.
- **Turno com erro é gravado** (`outcome="error"`), ao contrário da mensagem do assistente, que por decisão do M2 não é persistida quando o stream falha. Um turno que quebrou é exatamente o que se quer no trace.
- **O trace não duplica conteúdo.** Guarda a pergunta e *referências*: `message_id`, distâncias, contagens. Não guarda o texto da resposta (já está em `messages`) nem o conteúdo dos chunks (já está em `document_chunks`).
- **Nada de conteúdo confidencial novo.** O trace não introduz fonte de dado nova; só registra decisões sobre o que a base já continha (regra inegociável nº 4 intacta).

### 3. Modelo de dados

Subdomínio novo `src/domain/observability/` com Entity, Model, Mapper, Repository e Actions — Entity ≠ Model, conversão no Mapper (ADR-0003).

Migration `0006_agent_traces`. Tabela `agent_traces`:

| Coluna | Tipo | Nota |
|---|---|---|
| `uuid` | UUID PK | uuid7 |
| `conversation_id` | UUID FK → `conversations.uuid` | index |
| `message_id` | UUID \| null | mensagem do assistente, quando persistida |
| `user_email` | String(320) \| null | best-effort, como no M2 |
| `question` | Text | |
| `history_messages` / `history_tokens_est` | int | recência injetada |
| `gate_retrieve` | bool | index (agregação do split) |
| `gate_search_query` | String(512) \| null | a query reescrita |
| `gate_degraded` | bool | fail-open do gate |
| `gate_ms` | int | |
| `retrieval_ran` | bool | `false` quando o gate deu skip |
| `retrieval_top_k` | int | `RAG_TOP_K` vigente no turno (o que foi pedido) |
| `retrieval_kept` | int | quantos passaram do limiar |
| `retrieval_best_distance` | float \| null | ver "a distância do mais próximo" abaixo |
| `retrieval_threshold` | float | `RAG_MAX_DISTANCE` **no momento do turno** |
| `retrieval_ms` | int \| null | |
| `outcome` | String(16) | `answer` \| `refusal` \| `error` — index |
| `first_token_ms` / `engine_ms` | int \| null | |
| `citations_count` / `tool_calls` | int | |
| `input_tokens` / `output_tokens` | int \| null | ver incerteza acima |
| `error` | String(512) \| null | |
| `events` | JSONB | a sequência ordenada do turno |
| `created_at` / `updated_at` | timestamptz | mixin `HasTimestamps` |

Índice composto `(created_at DESC)` para a lista e os recortes de janela.

**Por que colunas planas *e* JSONB:** as colunas planas são o que o mapa agrega (`GROUP BY` em SQL, uma query); o `events` é o que o detalhe do turno exibe. Agregar sobre JSONB seria lento e ilegível; guardar só colunas planas perderia a ordem e a granularidade do detalhe. A duplicação é deliberada e vale a pena.

#### A distância do mais próximo

`search_similar` filtra pelo limiar **dentro do SQL** (decisão da spec de 2026-07-28: uma
query só, sem trazer linha que será descartada). Consequência: a Action não vê quantos
vizinhos foram rejeitados nem, quando **nada** passa, quão perto o mais próximo chegou — que
é exatamente o número que se quer diante de uma recusa ("faltou 0,01 ou faltou 0,3?").

Solução: manter a query filtrada no caminho normal e, **somente quando `retrieval_kept == 0`**,
rodar uma consulta diagnóstica mínima (`ORDER BY distance LIMIT 1`, sem `WHERE` de limiar)
para registrar `retrieval_best_distance`. Um método novo e explícito no repositório
(`nearest_distance(embedding) -> float | None`), chamado só no caminho de recusa — que por
definição não chamou o LLM e tem folga de sobra para uma query de índice.

Assim `retrieval_candidates` **não existe** como coluna: o número de rejeitados não é
observável sem desfazer a decisão de 07-28, e prometer a coluna seria prometer um dado que
não temos. Fica `retrieval_top_k` (o que foi pedido) + `retrieval_kept` (o que passou).

Forma de cada evento em `events`:

```json
[
  {"at_ms": 0,    "step": "turn_start",  "detail": {"question_chars": 18}},
  {"at_ms": 12,   "step": "recency",     "detail": {"messages": 4, "tokens_est": 830}},
  {"at_ms": 132,  "step": "gate",        "detail": {"retrieve": true, "search_query": "renovação de PSP", "degraded": false}},
  {"at_ms": 172,  "step": "retrieval",   "detail": {"top_k": 6, "kept": 2, "best_distance": 0.427, "threshold": 0.55}},
  {"at_ms": 410,  "step": "first_token", "detail": {}},
  {"at_ms": 1980, "step": "engine_done", "detail": {"citations": 2, "tool_calls": 0}},
  {"at_ms": 1998, "step": "turn_end",    "detail": {"outcome": "answer"}}
]
```

### 4. Endpoints

Somente leitura, em `src/app/api/routes/ops.py` (autodiscovery), com `OpsController` fino:

| Endpoint | Devolve |
|---|---|
| `GET /ops/overview?window=24h\|7d\|all` | tudo que o mapa precisa (ver abaixo) |
| `GET /ops/turns?window=&limit=50` | resumo dos turnos para a lista |
| `GET /ops/turns/{trace_id}` | o turno com a sequência de `events` |
| `GET /ops/eval` | último report + histórico, ou `{"status": "no_runs"}` |

`overview` agrega, para a janela pedida (`all` = sem filtro de data):

- **base:** documentos ativos, documentos arquivados (soft-deleted), chunks, lista de seções;
- **sync:** último registro de `job_executions` do `SyncKnowledgeBaseJob` (status, início, fim, erro);
- **gate:** contagem de `retrieve`, de `skip` e de `degraded`;
- **desfechos:** contagem de `answer`, `refusal` e `error`;
- **latência:** média e máximo de `first_token_ms` e de `engine_ms`;
- **retrieval:** média de `retrieval_kept`, média de `retrieval_best_distance`, e os valores vigentes de `RAG_TOP_K` e `RAG_MAX_DISTANCE`.

Quando a janela não tem nenhum turno, os agregados voltam zerados e a tela mostra estado vazio — não erro.

Duas fronteiras respeitadas:

- Os números da base vêm do subdomínio `documents` pela sua própria fronteira: a Action de ops **compõe** `ListKnowledgeSectionsAction` e uma `CountKnowledgeBaseAction` nova, em vez de tocar o `DocumentRepository` (regra nº 6, como a `AnswerQuestionAction` já faz).
- Ler `evals/reports/*` é I/O de infraestrutura: vai um `EvalReportStore` fino em `src/support/observability/` — mesmo lugar onde um exportador OTel entraria depois — e a Action compõe ele. Domínio não abre arquivo. O diretório vem de uma setting nova, `EVAL_REPORTS_DIR` (default `evals/reports`), porque o caminho depende de onde o processo roda e o diretório é gitignored — não pode ser hardcoded relativo ao módulo.

Agregação é **uma query com `GROUP BY`** no repositório, devolvendo um DTO. Nada de somar em Python.

### 5. A tela

Rota `/ops` na SPA, tema escuro dos `tokens.css` existentes, textos em pt-BR (identificadores em inglês, como manda a convenção do front). Seletor de janela (24h / 7d / tudo) no topo, afetando mapa e lista.

**Bloco 1 — mapa vivo.** Duas faixas de caixas, renderizadas do `ARCHITECTURE_MAP`:

- *Ingestão:* Notion MCP → curadoria → sync → limpeza/chunking → embeddings → `documents` / `chunks`.
- *Turno:* pergunta (SSE) → recência → **gate** → retrieval + limiar → **recusa** ou **engine + tools** → resposta → persistência → trace.

Cada caixa mostra os números da janela e abre, ao clique, um painel com o que faz, o arquivo que a implementa e os números detalhados.

**Bloco 2 — turnos recentes.** Lista com hora, pergunta, decisão do gate, chunks aprovados, desfecho e duração. Clicar abre a sequência do turno em ordem, cada etapa com o seu `at_ms`.

**Bloco 3 — eval.** Veredito do último run, média por métrica vs. threshold, `hard_failures` e histórico entre runs. Sem report, estado vazio dizendo qual comando rodar.

### 6. Encaixe da auth de admin

Um ponto de cada lado, os dois marcados com `TODO` amarrado à decisão de auth:

- **Backend:** dependency `require_admin` em `src/app/api/dependencies/`, aplicada ao router de ops. Hoje é no-op (passa direto). Quando a auth existir, ela levanta `NotFoundError` — que o `exception_handlers` já traduz para **404** — e não `UnauthorizedDomainError`/403: a página não deve nem revelar que existe.
- **Frontend:** `useCurrentUser()` expõe `isAdmin`, hoje sempre `true`. Ele decide se o link no header e a própria `<Route>` são montados. Não-admin não renderiza nada.

Esse é o mesmo `getCurrentUser()` que o design do frontend já previa como fast-follow — esta spec o cria com o campo `isAdmin` desde o começo, sem implementar auth.

## Onde cada peça mora

| Peça | Lugar |
|---|---|
| `TurnTrace` (Entity) | `src/domain/observability/entities/` |
| `TurnTraceModel` | `src/domain/observability/models/` |
| `TurnTraceDraft`, DTOs de agregado | `src/domain/observability/dtos/` |
| `TurnTraceRepository` (+ `summarize`) | `src/domain/observability/repositories/` |
| `RecordTurnTraceAction`, `ListRecentTracesAction`, `GetTurnTraceAction`, `GetOpsOverviewAction`, `ReadEvalReportAction` | `src/domain/observability/actions/` |
| `CountKnowledgeBaseAction` | `src/domain/documents/actions/` |
| `EvalReportStore` (filesystem) | `src/support/observability/` |
| `TurnMetrics` (parâmetro aditivo do engine) | `src/support/agent/ports.py` |
| `OpsController`, rota, responses | `src/app/api/` |
| `require_admin` | `src/app/api/dependencies/` |
| `ARCHITECTURE_MAP`, páginas e hooks | `frontend/src/features/ops/` |

## Compatibilidade

**Mudança quebrando:** `AnswerQuestionAction.execute` passa a devolver uma tripla
`(conversation_id, stream, draft)` em vez de uma dupla. Afeta o `ConversationController` e os
testes que hoje desempacotam dois valores
(`tests/unit/domain/conversations/actions/test_answer_question_action.py`,
`test_answer_question_out_of_scope.py`, `tests/integration/api/test_ask_endpoint.py`).
Aceitável e contido: um só chamador em produção.

O runner do eval **não** é afetado — ele já chama as peças do pipeline direto, sem passar pela
Action, exatamente para não persistir nada.

`OracleEngine.stream_answer` ganha parâmetro **opcional**; nenhum chamador existente muda.
A migration é aditiva (tabela nova) e não toca em nada existente. O contrato SSE não muda,
então o front do chat (`useAskStream`) não muda.

## Ordem de implementação

O plano deve seguir esta ordem, porque a tela sem dado não é testável de verdade:

1. Migration + subdomínio `observability` (Entity/Model/Mapper/Repository) — nada lê ainda.
2. `TurnTraceDraft` + coleta na `AnswerQuestionAction` + `nearest_distance` no repositório de chunks.
3. `TurnMetrics` no engine + preenchimento da fase de engine no controller + gravação pós-stream.
4. `CountKnowledgeBaseAction`, `EvalReportStore` e as Actions de leitura.
5. Endpoints de ops + `require_admin` no-op.
6. Frontend: `ARCHITECTURE_MAP` + teste do mapa honesto, depois os três blocos.

Ao fim do passo 3 já é possível fazer uma pergunta pelo chat e ver a linha em `agent_traces` —
esse é o marco que valida o desenho antes de existir tela.

## Testes

**Unitários (sem banco):**
- pureza do `TurnTraceDraft`: registra etapas em ordem, com `at_ms` monotônico;
- `AnswerQuestionAction` preenche gate e retrieval no draft (caminho retrieve e caminho skip);
- caminho de recusa → `outcome="refusal"`, `retrieval_ran=True`, `retrieval_kept=0`;
- caminho de erro → `outcome="error"` gravado, mensagem do assistente **não** gravada;
- **fail-safe:** `RecordTurnTraceAction` levantando não altera o stream nem propaga exceção;
- matemática dos agregados sobre linhas sintéticas;
- `EvalReportStore`: diretório ausente → estado vazio; JSON corrompido → erro claro;
- **teste do mapa honesto:** todo caminho do `ARCHITECTURE_MAP` existe no repo;
- `require_admin` hoje é no-op (o teste documenta o encaixe e falha se ele desaparecer).

**Integração (banco de teste):**
- depois de um `POST /conversations/ask` completo, existe uma linha em `agent_traces` com gate, retrieval e desfecho corretos — espelhando o teste que o M2 já tem para a mensagem do assistente;
- `nearest_distance` devolve a distância do vizinho mais próximo **ignorando o limiar**, e `None` quando não há chunk nenhum;
- `summarize` sobre linhas semeadas, por janela;
- shape dos quatro endpoints de ops.

**Frontend (Vitest):** hooks de ops, seletor de janela, estados vazios (sem turnos, sem eval) e o registro do mapa.

## Fora de escopo

- Acender ao vivo (broker/WebSocket/segundo canal SSE) — a decisão foi post-hoc.
- Export OpenTelemetry e ledger de custo em dinheiro (o guia do Waku §4.4 trata os dois; ficam para depois, e o `support/observability/` já é o lugar deles).
- Disparar eval pela web.
- A auth de admin propriamente dita — só o encaixe.
- Instrumentar o interior do job de sync; a página só lê a linha dele em `job_executions`.
- Tracing do runner de eval.
- Mudar `RAG_TOP_K`, limiar ou prompt por causa do que o trace mostrar (isso é a próxima conversa, com dado na mão).

## Riscos

- **O mapa envelhecer.** Mitigado pelo registro único + teste + regra no `CLAUDE.md`. É o risco assumido ao escolher desenho à mão em vez de Mermaid.
- **A tabela crescer sem poda.** Uma linha por turno, sem retenção na v1. No volume de um oráculo interno demora a importar, mas está registrado como follow-up em vez de silenciado.
- **A página expor pergunta de terceiros enquanto está aberta.** Decisão consciente do dono do produto: aberta até a auth existir, e o encaixe de admin já vem pronto nos dois lados.
- **`usage()` do pydantic-ai não entregar tokens no streaming.** Degradação prevista: v1 sem tokens, follow-up explícito.
- **Custo de latência da coleta.** O draft é acumulação em memória; a única escrita fica na background task pós-stream, fora do caminho da resposta. Sem custo perceptível para o usuário.
