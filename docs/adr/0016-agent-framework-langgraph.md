# ADR-0016 — Framework do agente = LangGraph, observabilidade fina no LangSmith

## Status

Aceito — 2026-09-01. Substitui [ADR-0007](0007-agent-framework-pydantic-ai.md).

## Resumo

- **Decisão:** o motor do oráculo passa a ser um `StateGraph` LangGraph em `src/support/agent/graph/` (nós `gate` · `retrieve` · `refuse` · `answer` + tool loop), consumido em **duas fases** por trás de `TurnGraphPort`. Tracing fino vai para o **LangSmith**; `agent_traces` continua com as colunas planas agregáveis.
- **Aplica-se quando:** for implementar ou evoluir a lógica do agente (roteamento, retrieval, tool calling, seleção de modelo, streaming) ou entender por que existe um consumo em duas fases em `runner.py`.
- **Regra prática:** o grafo mora inteiro em `support/agent/graph/`; `domain/` nunca importa `langgraph`/`langchain*` (protegido por `tests/unit/support/agent/test_domain_boundary.py`) — Actions de domínio entram no grafo como ports (`TurnDependencies`). Não há checkpointer: histórico continua em `conversations`/`messages`.

---

## Contexto

O [ADR-0007](0007-agent-framework-pydantic-ai.md) (02/07/2026) escolheu Pydantic AI e adiou o LangGraph por três razões técnicas: o fluxo do oráculo era um tool-loop único, não *graph-shaped*; a persistência do LangGraph (checkpointer) duplicaria Postgres + `conversations`; e o ecossistema LangChain tende a vazar abstrações que brigam com a arquitetura em camadas deste projeto.

Nenhuma dessas três razões mudou por mérito técnico entre julho e setembro. O que mudou foram os **drivers do projeto**, e este ADR os registra sem disfarce:

- **Case de portfólio.** O autor já tem vivência profissional com Pydantic AI. O objetivo aqui é ter, num projeto pessoal com arquitetura séria, um caso de uso real de LangGraph para conversa de entrevista técnica.
- **v2 multi-agente.** A evolução planejada do oráculo é multi-agente — cenário em que o LangGraph deixa de ser overkill e passa a ser a ferramenta certa.

Não é performance, e fabricar uma justificativa técnica seria mais frágil do que admitir o driver real numa conversa técnica — quem conhece as duas ferramentas percebe a diferença entre "migramos porque o grafo resolvia algo" e "migramos por decisão de carreira", e a segunda é defensável quando dita, a primeira não é quando checada.

## Decisão

Adotar **LangGraph** como motor do agente, com observabilidade fina delegada ao **LangSmith**.

### Os três motivos do ADR-0007 foram reavaliados, não negados

1. **"Não é graph-shaped"** — era verdade estruturalmente falsa desde o início: `AnswerQuestionAction` já tinha três decisões condicionais em série escritas à mão (gate → retrieve → limiar de recusa). O fluxo sempre foi um grafo; só não estava expresso como um. Migrar não introduz forma nova, só nomeia a que já existia.
2. **"O checkpointer duplicaria Postgres"** — **continua rejeitado, sem ressalvas**. Este ADR não adota checkpointer. `builder.py` monta o `StateGraph` sem um, e o histórico de conversa segue exclusivamente em `conversations`/`messages`. Fica para o v2 multi-agente, onde `interrupt()` para aprovação humana dá a ele um propósito real que hoje não existe.
3. **"Abstrações vazam"** — o risco é real e não foi eliminado, foi **contido**: as Actions de domínio (`SearchKnowledgeBaseAction`, `ListKnowledgeSectionsAction`, `build_out_of_scope_reply`) entram no grafo via Protocols em `src/support/agent/ports.py` (`KnowledgeSearchPort`, `KnowledgeSectionsPort`, `TurnDependencies`) sem precisar de nenhuma alteração — já satisfaziam a forma exigida. `domain/` nunca importa `langgraph` nem `langchain*`; a fronteira é `tests/unit/support/agent/test_domain_boundary.py`, que falha se algum arquivo em `src/domain/` importar o framework, e que também guarda contra a lista `_FORBIDDEN` virar tautologia (exige que `support/agent/` de fato use os pacotes proibidos).

### O grafo

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

Mapeia 1:1 o `if/else` que vivia em `AnswerQuestionAction` — nenhuma regra de negócio nova. Uma quarta aresta de entrada (`route_entry`) permite que o eval adversarial injete `knowledge` pré-semeado direto para `answer`, pulando gate e retrieve, sem precisar de um segundo grafo.

**Aresta `has_grounding` — o caso sutil.** Gate `degraded=True` (erro/timeout) com `knowledge` vazio vai para `answer`, não para `refuse`: o gate nunca chegou a classificar o turno, então `retrieve=True` nesse caminho é o chute de segurança do fail-open, não uma decisão fundamentada — recusar seria injustificado (ex.: "oi" durante um timeout do gate). Antes vivia como comentário de 12 linhas dentro de um `if`; agora é uma função pura em `edges.py`, testável isoladamente.

### A restrição de sessão e o consumo em duas fases

`DBSessionMiddleware` usa `BaseHTTPMiddleware`. Com ele, `call_next` retorna quando o `StreamingResponse` é *construído* — o corpo SSE é gerado depois, já fora do `async with` que mantém a sessão async viva. Quando o gerador de eventos do stream começa a rodar, a sessão do turno **já foi commitada e fechada**.

Isso não é um detalhe do LangGraph — é o LangGraph encontrando o ADR-0006 (sessão via ContextVar). O caminho óbvio, `graph.astream(...)` chamado inteiro dentro do gerador SSE, faria o nó `retrieve` chamar `CurrentAsyncSessionContext.get()` com a sessão já fechada, quebrando o turno de forma intermitente. Reforço colateral: repositórios capturam a sessão em `__init__`, então nada que dependa de repositório pode ser montado em tempo de import.

A resposta é `TurnGraphPort.start()` consumido em **duas fases**, implementado em `src/support/agent/graph/runner.py`:

- `AnswerQuestionAction.execute()` chama `await runner.start(...)`, que dirige o grafo com `stream_mode=["updates", "messages"]` até a **entrada do nó `answer`** (ou até a recusa, que não passa por LLM e chega via `updates`) — o critério é a entrada no nó, e não o primeiro token, porque uma resposta que abre só com `tool_calls` não produz token nenhum e deixaria o tool loop inteiro rodar com a conexão de banco presa — isso roda gate e retrieve **dentro** do escopo da sessão do request.
- `start()` devolve um gerador (`_resume`) que o controller consome no corpo do SSE, já fora da sessão. Dali em diante só há token de LLM e tool HTTP — as tools são deliberadamente HTTP-only, e o comentário em `tools.py` sobre rodarem "com segurança durante o streaming" é a invariante que a estrutura agora impõe, não uma observação.

O teste que protege essa invariante é o mais importante do lote: uma `search` fake que registra se rodou, com a asserção de que **ela já rodou** quando `start()` retorna, antes de qualquer iteração do gerador (`test_runner.py::test_gate_and_retrieval_run_before_the_generator_is_handed_off`). É a única defesa contra alguém "simplificar" o runner depois e reintroduzir o bug de sessão.

Duas alternativas foram descartadas por essa mesma restrição, não por gosto:

- **Grafo dono do stream inteiro dentro de `run_in_async_session`** — mais "LangGraph puro", mas segura uma conexão do pool do Postgres pela duração inteira do stream; clientes lentos esgotam o pool. Rejeitada por produção.
- **Dois grafos (planning + answering)** — elimina a sutileza do consumo em duas fases, mas divide a história em dois pedaços triviais e nenhum demonstra o pipeline completo — driver de case, não só de engenharia.

### Inversão de dependência via ports

`OracleEnginePort` e `RetrievalGatePort` (ADR-0007) se fundem em **`TurnGraphPort`**: a Action deixa de conhecer "gate" e "motor" como coisas separadas — agora são nós do mesmo grafo. `TurnDependencies` carrega as Actions de domínio injetadas (`search`, `sections`, `refusal`, `nearest`); `AnswerQuestionAction` monta esse objeto dentro do request, a seta de dependência continua `domain → support`, e `support/agent/` nunca importa `domain/`.

`TurnSignals` sucede `TurnMetrics`: absorve o que a Action media à mão e o que `draft.record(...)` gravava como JSON solto, num objeto tipado escrito pelos nós do grafo conforme o turno progride — mesmo padrão de sempre (objeto mutável instanciado pela Action, escrito por quem executa), sem mecanismo novo.

### As cinco dependências e o furo na regra 10

| | |
|---|---|
| Sai | `pydantic-ai` |
| Entra | `langgraph`, `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langsmith` |
| Fica | `anthropic`, `openai` (os wrappers usam os SDKs; o juiz do eval é sempre OpenAI direto) |
| Explicitado | `mcp` — já era dependência transitiva via `pydantic-ai`; sai do transitivo para o `pyproject.toml` porque `src/support/clients/notion/mcp_session.py` o usa diretamente |

Uma dependência sai, cinco entram (contando o `mcp` explicitado). Isso fura a **regra 10 do CLAUDE.md** de forma consciente — exatamente o motivo pelo qual o ADR-0007 havia rejeitado LangChain como núcleo. A decisão aqui assume o risco de churn de API do ecossistema LangChain em troca dos drivers descritos acima; não é isenção silenciosa da regra, é a exceção que este ADR autoriza.

Consequência observada, não hipotética: majors de dependências transitivas se moveram como efeito colateral da troca — `openai` 2.44 → 3.6, `mcp` 1.28 → 2.1. O que de fato foi verificado, e quando (correção de uma afirmação imprecisa da redação original desta ADR, que dava a entender que um eval completo havia rodado no momento da troca):

- **Na troca (01/09/2026):** conferência estática do juiz do eval contra a API do SDK `openai` 3.6 — formato de chamada e de resposta — mais a suíte de testes. Não houve eval completo naquele momento.
- **Em 02/09/2026, depois do corte:** o eval completo rodou contra o grafo **e** contra `openai` 3.6, com chamadas reais. Resultado idêntico ao baseline pré-migração — faithfulness 1.00 (n=9), appropriate_refusal 1.00 (n=5), citation_support 1.00 (n=7); delta 0.00 nas três métricas, nenhum caso abaixo do piso.
- **Ainda não verificado:** o comportamento do `mcp` 2.1 contra o Notion real numa sincronização de produção. Fica registrado como ponto a observar no primeiro sync pós-deploy, não como risco mitigado — o eval não exercita esse caminho.

### LangSmith

`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` nas `Settings`, default desligado, seguindo o padrão de `ENABLE_SCHEDULER`. Tracing de LangGraph é configuração, não integração: o grafo aparece lá com nós, arestas percorridas, prompts, I/O de tool, latência por nó e custo, sem código de instrumentação manual.

Divisão de responsabilidade, para não duplicar UI (que é o que custa caro — dado duplicado num SaaS é grátis, um componente React que renderiza pior o que o LangSmith já renderiza cobra manutenção para sempre):

- **LangSmith:** detalhe fino dentro do run — spans, prompts, I/O de tool, tokens, custo, replay.
- **`agent_traces` (Postgres):** colunas planas agregáveis — decisão do gate, outcome, distância do retrieval, latências, contagens. Redundantes com o LangSmith por design: são o que torna `GROUP BY` possível (ex.: taxa de recusa numa janela), o que o LangSmith não pode calcular porque depende do limiar e das distâncias específicas deste projeto.
- A página de Ops ganha um deep link para o run do LangSmith a partir do detalhe do turno; o renderizador de eventos passo-a-passo do `TurnDetail` (que existia porque não havia alternativa melhor) foi removido a favor desse link.

**`user_email`:** o trace carrega o e-mail vindo do header `cf-access-authenticated-user-email` — PII de pessoa real. Ele vai ao LangSmith **apenas como hash estável** (permite agrupar por usuário sem expor identidade); o e-mail em claro permanece exclusivamente em `agent_traces`, nunca sai da aplicação.

## Consequências

**Positivas**

- Grafo demonstrável como caso de uso real de LangGraph — cumpre o driver de portfólio.
- Base pronta para o v2 multi-agente, onde o LangGraph é a ferramenta adequada (não overkill).
- As três decisões condicionais do turno viram funções puras testáveis (`edges.py`) em vez de comentário dentro de `if`.
- Observabilidade fina "de graça" via LangSmith, sem instrumentação manual — spans, custo e replay por turno.
- Fronteira de domínio permanece protegida por teste automatizado, e mais rigorosamente do que antes: o teste anterior (`test_oracle_engine_boundary.py`) só exercitava um fake e nunca provou a ausência do import.

**Negativas / riscos**

- **Boot mais pesado.** O grafo é compilado uma vez no módulo (`TURN_GRAPH` em `builder.py`) para não recompilar por turno, mas o import de `langgraph`/`langchain*` soma custo de startup que Pydantic AI não tinha.
- **Ecossistema com churn.** LangChain historicamente quebra compatibilidade entre minors; a mitigação é a mesma que já existia — o núcleo do agente fica contido em `support/agent/`, isolado do domínio.
- **Uma dependência a mais para auditar** (efetivamente cinco entrando por uma saindo, ver seção de dependências), com o `mcp` saindo do estado transitivo para explícito.
- **Extração de tokens em streaming permanece frágil.** No LangChain a leitura é `usage_metadata` em `AIMessage`, mais estável que a adivinhação de campo entre versões que o Pydantic AI exigia, mas ainda depende de flag por provider (`stream_usage`) e difere entre Anthropic e OpenAI. Princípio mantido: se o token não vier, o trace fica sem ele em vez de derrubar o turno.
- **Compatibilidade de majors não observada em produção real.** `openai` e `mcp` subiram de major como efeito colateral. O `openai` 3.6 foi exercitado de ponta a ponta pelo eval completo de 02/09/2026 (delta 0.00 contra o baseline); o `mcp` 2.1 só passou pelos testes — seu comportamento contra o Notion real ainda não foi visto numa sincronização de produção.

## Alternativas consideradas

- **Manter Pydantic AI, adicionar Pydantic Graph.** Resolveria a forma graph-shaped sem trocar de ecossistema, mas não atende o driver real (case de portfólio com LangGraph especificamente) — rejeitada porque a decisão não é sobre forma, é sobre qual ferramenta o autor precisa ter usado de verdade.
- **Grafo com stream inteiro dentro da sessão (`run_in_async_session`).** Ver seção "consumo em duas fases" acima — rejeitada por esgotar o pool de conexões sob clientes lentos.
- **Dois grafos separados (planning/answering).** Ver mesma seção — rejeitada por fragmentar a demonstração do pipeline em duas partes triviais.
- **Checkpointer do LangGraph para o histórico da conversa.** Deliberadamente fora de escopo — duplicaria `conversations`/`messages` como fonte da verdade. Fica para o v2, onde `interrupt()` para aprovação humana dá a ele propósito genuíno.
