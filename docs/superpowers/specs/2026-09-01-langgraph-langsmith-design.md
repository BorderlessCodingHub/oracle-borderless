# Motor do oráculo migra para LangGraph, observabilidade fina vai para o LangSmith

Data: 2026-09-01
Origem: brainstorm Duanne <> Claude, 01/09/2026.
Substitui: ADR-0007 (framework do agente) — via ADR-0016, a ser escrito na fase 4.

## Contexto

O ADR-0007 (02/07/2026) escolheu **Pydantic AI** como motor do agente e adiou
explicitamente o LangGraph, com três razões:

1. o fluxo do oráculo era um tool-loop único, não algo *graph-shaped*;
2. a persistência do LangGraph (checkpointer) duplicaria Postgres +
   `conversations`;
3. abstrações do ecossistema LangChain tendem a vazar e brigar com a arquitetura
   em camadas.

Nenhuma das três mudou por mérito técnico. O que mudou são os **drivers do
projeto**:

- **Case de portfólio.** O autor já tem vivência de Pydantic AI em projetos
  profissionais e quer um projeto pessoal onde LangGraph seja usado de verdade,
  como artefato de entrevista.
- **v2 multi-agente.** A evolução prevista para o oráculo é multi-agente, cenário
  em que o LangGraph deixa de ser overkill e passa a ser a ferramenta adequada.

Isso é requisito de projeto legítimo, e esta spec o trata como tal — sem
fingir que a motivação é performance ou que o desenho atual está errado.

Uma consequência direta do driver "case": **a migração barata é a que não serve.**
Trocar apenas o motor por um grafo de um nó custaria 1–3 dias e não demonstraria
LangGraph nenhum — é um wrapper de `ChatModel`, identificável em segundos por
quem conhece a ferramenta. Se o objetivo é case, o grafo tem que conter o
pipeline de decisão inteiro.

E uma contra-restrição igualmente importante: **a arquitetura do projeto também é
o case.** Camadas Spatie-like, Entity≠Model, ports, 15 ADRs com racional, trace
próprio em Postgres e harness de eval com judge são sinal sênior mais forte do
que a adoção de um framework. O desenho abaixo existe para obter o grafo **sem**
erodir isso.

## O risco central descoberto no brainstorm

`DBSessionMiddleware` usa `BaseHTTPMiddleware`. Com ele, `call_next` retorna
quando o `StreamingResponse` é *construído*; o corpo SSE é gerado depois, já fora
do `async with`. **Quando o gerador de eventos começa a rodar, a sessão async já
foi commitada e fechada.**

O desenho atual é inteiramente uma resposta a isso:

- `AnswerQuestionAction.execute()` grava conversa e mensagem do usuário **antes**
  de retornar;
- o retrieval roda **dentro** de `execute()`, não durante o stream;
- as tools são HTTP-only por decisão — o comentário em `tools.py` ("não tocam o
  banco, então rodam com segurança durante o streaming") é a invariante, não uma
  observação;
- a persistência pós-stream abre sessão própria via `run_in_async_session`.

**Consequência para a migração:** invocar `graph.astream(...)` dentro do gerador
SSE — o caminho natural, e o que qualquer tutorial de LangGraph mostra — faria o
nó de retrieval chamar `CurrentAsyncSessionContext.get()` com a sessão fechada,
quebrando o turno de forma intermitente. Esta é a complexidade escondida da
refatoração: não é o LangGraph, é o LangGraph encontrando o ADR-0006.

Reforço colateral: repositórios capturam a sessão **na construção**
(`self.session = CurrentAsyncSessionContext.get()` em `__init__`). Logo, nada que
dependa de repositório pode ser montado em tempo de import.

## Decisão

Um `StateGraph` único em `src/support/agent/graph/` contém o pipeline de decisão
do turno — gate, retrieval, limiar/recusa, resposta e tool loop. Ele é consumido
em **duas fases**: `AnswerQuestionAction.execute()` dirige o grafo até o primeiro
token, dentro do escopo da sessão; o controller consome o restante no SSE, quando
só há token de LLM e tool HTTP. As Actions de domínio entram no grafo
**injetadas como ports**. O LangSmith recebe o detalhe fino do run; a página de
Ops mantém e amplia o que o LangSmith estruturalmente não vê.

### Abordagens rejeitadas

- **Grafo dono de tudo, stream inteiro dentro de `run_in_async_session`.** Mais
  "LangGraph puro" e mais simples de escrever, mas segura uma conexão do pool do
  Postgres pela duração inteira do stream — clientes lentos esgotam o pool. Além
  de esvaziar `AnswerQuestionAction` e transformar a regra 6 em letra morta.
  Rejeitada por produção, não por pureza.
- **Dois grafos (planning via `ainvoke` + answering via `astream`).** Elimina a
  sutileza do consumo em duas fases e cada grafo fica trivial de testar, mas
  divide a história do case: roteamento condicional num grafo, tool loop no
  outro, e nenhum dos dois isolado demonstra o pipeline.
- **Checkpointer / HITL nesta fase.** É a feature mais distintiva do LangGraph,
  mas duplica estado com `conversations`/`messages` e exige decidir quem é a
  fonte da verdade. Fica para o v2, junto com o multi-agente, onde ela ganha
  propósito real (`interrupt()` para aprovação humana).

## Fora de escopo

- **Regras de negócio.** O grafo é tradução 1:1 do `if/else` atual. Nenhum
  comportamento novo — se o eval regredir, é bug de tradução.
- **Contrato SSE.** `AgentStreamChunk` (`text` | `sources`) permanece idêntico.
  Frontend do chat não é tocado.
- **`SYSTEM_PROMPT`, chunking, embeddings, limiar de distância, curadoria,
  ingestão.** Intocados.
- **Autenticação.** Continua fora.
- **Migrar o eval para datasets do LangSmith.** Fast-follow (ver "Sequência").
  O harness atual é a rede de segurança do big-bang e não pode mudar junto.
- **`EvalPanel` / `read_eval_report_action`.** Ficam, pelo mesmo motivo.

## 1. Estrutura de arquivos

```
src/support/agent/
├── ports.py              # ampliado: ports de domínio, TurnDependencies, TurnGraphPort
├── prompts.py            # inalterado
├── tools.py              # WebSearchTool / FetchNotionTool inalterados; só o registro muda
├── models.py             # NOVO — seleção de provider num ponto único
└── graph/
    ├── state.py          # TurnState
    ├── nodes.py          # gate · retrieve · refuse · answer
    ├── edges.py          # should_retrieve · has_grounding
    ├── builder.py        # build_turn_graph() -> CompiledStateGraph
    └── runner.py         # TurnGraphRunner — implementa TurnGraphPort, consumo em 2 fases
```

Deletados: `oracle_engine.py`, `retrieval_gate.py`. O `models.py` recolhe num só
lugar os dois `_build_model()` hoje duplicados entre motor e gate.

## 2. O grafo

```
                  ┌─────────┐
        START ───►│  gate   │  modelo pequeno, structured output, fail-open
                  └────┬────┘
                       │ should_retrieve
              ┌────────┴────────┐
       retrieve=false      retrieve=true
              │                 │
              │            ┌────▼─────┐
              │            │ retrieve │  pgvector top-k + limiar
              │            └────┬─────┘
              │                 │ has_grounding
              │        ┌────────┴────────┐
              │   vazio & !degraded    tem contexto
              │        │                 │
              │   ┌────▼────┐            │
              │   │ refuse  │            │
              │   └────┬────┘            │
              │        │                 │
              └────────┼─────────────►┌──▼─────┐
                       │              │ answer │◄──┐
                       │              └──┬─────┘   │
                       │      tools_condition│     │
                       │              ┌──────┴───┐ │
                       │              │  tools   │─┘
                       ▼              └──────────┘
                      END ◄───────────────┘
```

Mapeia 1:1 o `if/else` de `answer_question_action.py`.

`TurnState` (TypedDict): `question`, `history`, `retrieve`, `search_query`,
`degraded`, `knowledge`, `answer`, `citations`, `outcome`.

**Aresta `has_grounding` — o caso sutil.** Gate `degraded=True` com `knowledge`
vazio vai para `answer`, **não** para `refuse`: um gate que estourou timeout
nunca classificou o turno, então `retrieve=True` ali é chute de fail-open, não
decisão fundamentada — recusar seria injustificado (ex.: "oi" durante um
timeout). Hoje isso é protegido por um comentário de 12 linhas dentro de um `if`;
como aresta, vira teste.

## 3. Inversão de dependência

`support/` não pode importar `domain/`. Então `ports.py` ganha:

```python
class KnowledgeSearchPort(Protocol):
    async def execute(self, query: str, top_k: int | None = None) -> list[KnowledgeSnippet]: ...

class KnowledgeSectionsPort(Protocol):
    async def execute(self) -> list[str]: ...

@dataclass
class TurnDependencies:
    search: KnowledgeSearchPort
    sections: KnowledgeSectionsPort
    refusal: Callable[[list[str], str], str]
```

`SearchKnowledgeBaseAction`, `ListKnowledgeSectionsAction` e
`build_out_of_scope_reply` **já satisfazem esses protocolos como estão** — zero
linha alterada no domínio para a injeção funcionar. `AnswerQuestionAction` monta o
`TurnDependencies`; a seta de dependência continua `domain → support`.

`OracleEnginePort` e `RetrievalGatePort` se fundem em **`TurnGraphPort`**: a
Action deixa de conhecer "gate" e "motor" como coisas separadas, porque agora são
nós do mesmo grafo.

### `TurnMetrics` → `TurnSignals`

O `TurnMetrics` atual (`tool_calls`, `input_tokens`, `output_tokens`) é estendido
e renomeado para **`TurnSignals`**, absorvendo o que a Action media à mão e os
`draft.record(...)` cobriam: `gate_retrieve`, `gate_search_query`,
`gate_degraded`, `gate_ms`, `retrieval_ran`, `retrieval_kept`, `retrieval_ms`,
`retrieval_best_distance`, `outcome`.

É o **mesmo padrão que já existe** — objeto mutável instanciado pela Action e
escrito por quem executa —, só que agora quem escreve são os nós do grafo em vez
do corpo da Action. Não é mecanismo novo: é o `TurnMetrics` fazendo o trabalho
que o `draft.record()` fazia, num objeto tipado em vez de JSON solto.

`AnswerQuestionAction` instancia o `TurnSignals`, guarda a referência no
`TurnTraceDraft` e o passa no `config`; o controller lê dele no fim do stream
para preencher as colunas planas do trace.

## 4. Grafo compilado uma vez, dependências por turno

Como repositórios capturam a sessão em `__init__`, `TurnDependencies` precisa
nascer dentro do request. Mas compilar o `StateGraph` por turno é desperdício.
Logo: **estrutura compilada uma vez no módulo; tudo volátil viaja no `config`.**

```python
_GRAPH = build_turn_graph()          # módulo, uma vez

config = {"configurable": {
    "deps": TurnDependencies(...),    # repos com a sessão deste request
    "signals": signals,               # preenche as colunas planas do trace
    "citations": web_citations,        # coletor do WebSearchTool
}}
```

Resolve de uma vez sessão-por-request, coleta de citações web e preenchimento do
trace, sem estado global e sem recompilar.

## 5. Consumo em duas fases

```python
# runner.py
async def start(self, question, history, config) -> AsyncIterator[AgentStreamChunk]:
    signals = config["configurable"]["signals"]
    agen = _GRAPH.astream(state, stream_mode=["updates", "messages"], config=config)
    first = None
    async for mode, payload in agen:
        if mode == "updates":
            _absorb(signals, payload)      # gate_ms, retrieval_kept, outcome, degraded...
            first = _refusal_text(payload)  # nó refuse não emite "messages"
            if first:
                break
            continue
        first = _to_chunk(payload)          # token do LLM
        if first:
            break
    return _resume(first, agen, config)     # emite `first`, depois continua
```

`await runner.start(...)` executa **gate e retrieve com a sessão viva** e para no
primeiro token. Devolve o gerador; o controller continua no SSE, quando restam só
tokens e tools HTTP. A invariante de sessão passa de comentário implícito a
estrutura explícita.

- **`stream_mode=["updates", "messages"]`** é o que torna isso possível:
  `messages` dá os tokens, `updates` dá o resultado de cada nó. Sem os dois, ou
  se perde o streaming ou se perde o trace.
- **O nó `refuse` não produz `messages`** — é texto determinístico, sem LLM.
  Chega por `updates` e o runner sintetiza o `AgentStreamChunk`. É o que mantém a
  recusa instantânea, como o ADR-0013 registra.
- **`sources`** sai no fim: `[s.citation for s in state["knowledge"]] +
  config["citations"]`.

### Correção necessária no controller

Hoje ele distingue recusa de resposta por `draft.engine_metrics is not None`.
Como agora **os dois caminhos passam pelo grafo**, isso vira
`signals.outcome == "answer"`. Sem essa troca, `first_token_ms` e `engine_ms` da
recusa entram na média da página de ops — precisamente o bug que o comentário em
`conversation_controller.py:66-72` diz ter sido corrigido numa revisão anterior.

## 6. O que sobra em `AnswerQuestionAction`

Fica: resolver/criar conversa, `ConversationAccessPolicy`, gravar mensagem do
usuário, carregar recência, montar `TurnDependencies`, chamar o grafo, devolver
`(conversation_id, stream, draft)`.

Sai: gate, retrieval, decisão de limiar, e todos os `draft.record(...)`.

De ~150 para ~70 linhas — volta a ser composição, como as regras 5 e 6 descrevem.

## 7. Falhas

| Falha | Hoje | No grafo |
|---|---|---|
| Gate erra / estoura timeout | `try/except` → fail-open, `degraded=True` | Igual, dentro do nó; `asyncio.wait_for(GATE_TIMEOUT_SECONDS)` permanece |
| Tool HTTP falha | texto de erro embrulhado, stream segue | Igual — `try/except` dentro da tool, não no `ToolNode` |
| Retrieval falha | exceção sobe, turno quebra | Agora quebra **durante `execute()`**, dentro da sessão, e o rollback do middleware pega. Melhor que hoje |
| LLM falha no meio do stream | `except` no controller → `outcome="error"`, trace gravado | Igual |

**Incerteza registrada:** extração de tokens em streaming. O `_fill_usage()`
atual adivinha nomes de campo entre versões do pydantic-ai. No LangChain a
leitura é `usage_metadata` no `AIMessage` — mais estável —, mas em streaming
depende de flag por provider (`stream_usage`) e difere entre Anthropic e OpenAI.
A validar na implementação, com o princípio de hoje preservado: **se não vier, o
trace fica sem tokens em vez de derrubar o turno.**

## 8. Observabilidade — divisão de responsabilidade

A duplicação que custa caro não é a de dados; é a de UI e manutenção. Dado
duplicado num SaaS não cobra nada. Um componente React que renderiza o que o
LangSmith renderiza melhor cobra para sempre.

| | LangSmith | Página de Ops |
|---|---|---|
| Detalhe dentro do run (spans, prompts, I/O de tool, tokens, custo, replay) | ✅ | ❌ |
| Datasets, eval versionado, annotation queue | ✅ (fast-follow) | ❌ |
| Ingestão, KB, curadoria, sync | ❌ | ✅ |
| Agregados de negócio por janela | ❌ | ✅ |
| Mapa de arquitetura honesto | ❌ | ✅ |

`agent_traces` fica com as colunas planas (decisão do gate, outcome, distância,
latências, contagens). São redundantes com o LangSmith, mas são o que torna
`GROUP BY` possível — sem elas não existe "taxa de recusa nesta janela". E são
colunas baratas, com retenção que é sua.

### Instrumentação

`LANGSMITH_TRACING: bool = False`, `LANGSMITH_API_KEY: str | None`,
`LANGSMITH_PROJECT: str = "oracle-borderless"` nas `Settings` — nunca lidas de
`os.environ` solto, seguindo o padrão de injeção de chave que `_build_model()` já
usa. Default desligado, ligado por `.env`, como `ENABLE_SCHEDULER`.

Traçar LangGraph é configuração, não integração: o grafo aparece no LangSmith com
nós, arestas percorridas, prompts, I/O de tool, latência por nó e custo, de graça.

**`user_email`:** o trace carrega o e-mail vindo do header
`cf-access-authenticated-user-email` — PII de pessoa real. Vai ao LangSmith
apenas como **hash estável** (agrupa por usuário sem expor identidade); o e-mail
em claro permanece só em `agent_traces`.

### Deleções

| Item | Por quê |
|---|---|
| `TurnTrace.events` + coluna JSON | É a sequência passo-a-passo — o que o LangSmith faz melhor |
| `draft.record(...)` (7 chamadas) | Some junto com o campo |
| Renderizador de eventos do `TurnDetail` | Vira deep link para o run |

Migration Alembic em `agent_traces`: **+ `langsmith_run_id`**, **− `events`**.

### Adições na Ops

Todas SQL sobre dados que **já existem**, nenhuma reproduzível no LangSmith:

1. **Lacunas da base.** As recusas já gravam `retrieval_best_distance`. Ordenar
   as perguntas recusadas cujo melhor vizinho ficou logo acima de
   `RAG_MAX_DISTANCE` produz uma lista rankeada do que a KB não cobre mas quase
   cobria — a resposta operacional para "o que falta ingerir?". O LangSmith não
   pode calcular isso: depende do seu limiar e das suas distâncias.
2. **Distribuição do gate na janela.** `% retrieve` / `% skip` / `% degraded`.
   Colunas já existem. `degraded` subindo é timeout do modelo pequeno — hoje
   invisível.
3. **Mapa de arquitetura refletindo o grafo.** A caixa `engine` ("Pydantic AI")
   vira as caixas dos nós, apontando para `graph/nodes.py`, `graph/edges.py`,
   `graph/runner.py`. **Obrigatório** pela regra do `CLAUDE.md` (mesmo commit), e
   `architectureMap.test.ts` é o que avisa se `oracle_engine.py` não foi deletado.

## 9. Dependências

| | |
|---|---|
| Sai | `pydantic-ai>=2.4.0` |
| Entra | `langgraph`, `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langsmith` |
| Fica | `anthropic`, `openai` (os wrappers usam os SDKs; o juiz é sempre OpenAI) |

Uma sai, cinco entram. Isso fura a **regra 10** e assume o risco de churn de API
— exatamente o motivo pelo qual o ADR-0007 rejeitou LangChain. O ADR-0016 tem que
justificar isso de forma explícita, não silenciosa.

## 10. Testes

**Tradução.** `pydantic_ai.models.test.TestModel` → `GenericFakeChatModel` /
`FakeListChatModel` do `langchain_core`, em 8 arquivos (~427 linhas). É o pedaço
mais chato e mais previsível.

**Atualização crítica.** `test_oracle_engine_boundary.py` passa a provar que
`src/domain/` não importa `langgraph` nem `langchain*`. Sem ele, a injeção via
ports vira boa intenção.

**Novos:**

- **Arestas** (`should_retrieve`, `has_grounding`) — funções puras. Inclui o caso
  do gate `degraded` com knowledge vazio indo para `answer`.
- **Consumo em duas fases** — o mais importante de todos: uma `search` fake que
  registra se rodou, e a assertiva de que **ela já rodou** quando `start()`
  retorna, antes de qualquer iteração do gerador. É a única defesa contra alguém
  "simplificar" o runner mais tarde e reintroduzir o bug de sessão.
- **Nós isolados** — cada nó com `deps` fake, hoje impossível porque gate e
  retrieval estão soldados na Action.

## 11. Sequência de corte — a ordem importa

`evals/judge/judge.py` usa `pydantic_ai`. Se o juiz mudar no mesmo PR que o
motor, o baseline do eval não vale nada: não se sabe se a variação veio do grafo
ou do juiz.

| # | Passo | Verificação |
|---|---|---|
| 0 | Rodar o eval no motor atual; commitar `eval_report.json` | Baseline congelado em git |
| 1 | Migrar só o juiz para o SDK `openai` direto (é sempre OpenAI — sai um framework do caminho do eval) | Rodar o eval **no motor atual**; scores batem com o passo 0 |
| 2 | Big-bang do grafo; deletar `oracle_engine.py` e `retrieval_gate.py`; traduzir testes | `pytest` verde + eval comparado ao passo 1 |
| 3 | LangSmith, `langsmith_run_id`, migration (`− events`), deleções e adições na Ops | `alembic check` limpo; `architectureMap.test.ts` verde |
| 4 | ADR-0016; docs | — |

O passo 1 é o que transforma "big-bang com o eval como rede" de intenção em fato.

## 12. Docs a atualizar

ADRs são imutáveis, então:

- **ADR-0016** novo: drivers (case + v2 multi-agente), o grafo, as 5
  dependências, o LangSmith, e por que os três motivos do ADR-0007 foram
  reavaliados em vez de negados.
- **ADR-0007**: Status marcado `Superseded por ADR-0016`.
- **`docs/adr/README.md`**: índice.
- **`docs/architecture.md`**: seção do agente.
- **`frontend/src/features/ops/architectureMap.ts`**: caixas do grafo.
- **`CLAUDE.md`**: a seção de stack hoje diz *"exclusivamente pelo Pydantic AI
  dentro de `src/support/agent/` (`oracle_engine.py` para a resposta,
  `retrieval_gate.py` para o gate)"* — nomeia dois arquivos que deixarão de
  existir.

## 13. Esforço

| Fase | Estimativa |
|---|---|
| Passos 0–1 (baseline + juiz) | ~0,5 dia |
| Passo 2 (grafo + testes) | 5–7 dias |
| Passo 3 (LangSmith + Ops) | 2–3 dias |
| Passo 4 (ADR + docs) | ~0,5 dia |
| **Total** | **~8–11 dias de trabalho focado** |

O grafo é o grosso; dentro dele, o runner de duas fases é o único pedaço
genuinamente difícil. O resto é tradução mecânica.

## 14. Critérios de aceite

- `pytest` verde, incluindo o teste de fronteira provando que `src/domain/` não
  importa `langgraph`/`langchain*`.
- Teste que prova que gate e retrieval executaram **antes** de `start()`
  devolver o gerador.
- Eval comparado ao baseline do passo 1, sem regressão de qualidade atribuível
  ao grafo.
- `alembic check` limpo.
- `architectureMap.test.ts` verde, com as caixas do grafo apontando para arquivos
  existentes.
- `grep -r pydantic_ai src/` sem resultado.
- Contrato SSE inalterado: frontend do chat funciona sem alteração.
- Run do LangSmith alcançável a partir do detalhe do turno na página de Ops.
- Nenhum `user_email` em claro no LangSmith.

---

**Nota (2026-09-04).** O contrato de saída do runner mudou com a spec
`2026-09-04-ag-ui-turno-design.md` / ADR-0019: `AgentStreamChunk` virou uma
união com passos e tool calls, e o controller passou a emitir eventos AG-UI. O
consumo em duas fases (seção 5) e o tratamento de falhas (seção 7) descritos
aqui continuam valendo.
