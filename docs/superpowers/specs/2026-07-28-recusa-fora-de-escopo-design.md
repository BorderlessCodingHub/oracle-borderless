# Design — Recusa explícita quando a pergunta não está na base

**Data:** 2026-07-28
**Status:** aprovado (aguardando plano de implementação)
**Depende de:** [ADR-0012](../../adr/0012-escopo-kb-aplicado-na-recuperacao.md) — a coluna de procedência e a migration vêm de lá.

## Problema

Depois da reconciliação da KB para o subtree de "Products" (562 → 42 documentos),
uma pergunta fora do escopo **continua recebendo uma resposta**. Não porque o
conteúdo fora do escopo ainda esteja lá — está soft-deleted — mas porque
[`search_similar`](../../../src/domain/documents/repositories/document_chunk_repository.py)
sempre devolve os `RAG_TOP_K` vizinhos mais próximos, **sem limiar de distância**.

Pergunta sobre bolo de cenoura recupera os 6 chunks de Products menos distantes e
os injeta como contexto. O único guarda-corpo é a regra nº 2 do
[system prompt](../../../src/support/agent/prompts.py) ("se não houver fonte que
sustente a resposta, diga que não está na base") — ou seja, a honestidade do
oráculo depende inteiramente do julgamento do LLM sobre um contexto que o sistema
afirmou ser relevante ao entregá-lo.

A dona do produto quer o comportamento explícito: quando a pergunta não está
coberta, dizer que não encontrou **e** explicar sobre o que o oráculo responde.

## Calibração (medida em 2026-07-28, base já reconciliada)

Distância cosseno do melhor chunk, por tipo de pergunta:

| Pergunta | Distância | Grupo |
|---|---|---|
| o que é o Web3 Bootcamp? | 0.309 | dentro |
| quais são as entregáveis da mentoria PSP? | 0.419 | dentro |
| quando é a edição #02 do bootcamp? | 0.423 | dentro |
| **qual é o processo de renovação do PSP?** | **0.427** | **fora (Ops)** |
| o que é o BASE Gate? | 0.455 | dentro |
| **como funciona o onboarding de novo mentorado?** | **0.461** | **fora (Ops)** |
| como funciona a mentoria BASE? | 0.467 | dentro |
| o que é o PSP? | 0.482 | dentro |
| quais programas existem no ecossistema? | 0.532 | dentro |
| ⎯⎯ *corte proposto: 0.55* ⎯⎯ | | |
| como criar eventos no Discord? | 0.574 | fora (Ops) |
| o que diz o SOP-GM-01…? | 0.598 | fora (Ops) |
| qual o melhor framework de frontend? | 0.615 | nada a ver |
| qual a convenção de UTM para campanhas? | 0.633 | fora (Ops) |
| quem ganhou a copa de 2022? | 0.667 | nada a ver |
| como faço um bolo de cenoura? | 0.697 | nada a ver |
| qual a capital da Austrália? | 0.813 | nada a ver |

Leitura: um corte em **0.55** deixa passar as **7** perguntas legítimas
(máx. 0.532) e barra as **4** sem relação nenhuma (mín. 0.615), com folga nos dois
lados. Das 5 perguntas de Ops, **3 caem acima do corte** (Discord, SOP, UTM) e
**2 ficam abaixo** — são exatamente os casos ambíguos tratados pela camada 2.

**Mas o limiar sozinho não basta.** "Renovação do PSP" (0.427) e "onboarding de
mentorado" (0.461) são perguntas de Ops — fora do escopo — que pontuam *melhor*
que uma pergunta legítima, porque compartilham vocabulário com páginas de
Products. Nenhum limiar separa esses casos sem passar a recusar pergunta boa.
Daí o desenho em duas camadas.

## Decisões

1. **Limiar de distância + julgamento do LLM no que passa.** O corte mecânico
   elimina o óbvio; o modelo decide se o contexto que sobrou realmente responde.
2. **Lista de temas derivada da KB**, não texto fixo — não envelhece quando a
   árvore do Notion muda.
3. **Recusa determinística, sem chamada de LLM**, em pt-BR e inglês.

## Desenho

### 1. Limiar na recuperação

`settings.RAG_MAX_DISTANCE` (novo, default `0.55`).
`DocumentChunkRepository.search_similar` ganha
`.where(DocumentChunkModel.embedding.cosine_distance(embedding) <= limite)`.

Filtrar em SQL (e não em Python depois) mantém uma única query e evita trazer
linhas que serão descartadas. O `ORDER BY` já existente continua.

### 2. Gatilho da recusa — com a guarda do gate

Em [`AnswerQuestionAction`](../../../src/domain/conversations/actions/answer_question_action.py),
recusar **somente quando `decision.retrieve` é `True` e o resultado filtrado é
vazio**.

A guarda é essencial: `retrieve=False` (saudações, agradecimentos, perguntas
sobre o próprio oráculo) também produz `knowledge = []`, e esses turnos devem
seguir para o motor normalmente. Sem a guarda, "oi" recebe "não encontrei
informações" — regressão pior que o bug original.

### 3. Recusa determinística

Quando o gatilho dispara, a Action devolve um stream pré-montado no lugar de
`engine.stream_answer(...)`:

- emite o texto como chunks `type="text"`;
- emite `type="sources"` com lista vazia.

O contrato SSE não muda, então
[`useAskStream.ts`](../../../frontend/src/hooks/useAskStream.ts) não muda. O
`ConversationController` já captura o texto emitido e persiste a mensagem do
assistente, então a recusa entra na memória episódica como qualquer resposta —
sem código novo no controller.

Ganho: resposta instantânea, custo zero de LLM, e a cópia é exatamente a definida
aqui (o modelo não parafraseia).

### 4. Origem da lista de temas

Os filhos diretos do root são os temas. Verificado via MCP em 2026-07-28 — o root
"Products" tem exatamente 5 blocos `child_page` (os demais são parágrafos vazios):

**Mentorship · Bootcamps · Programs · Masterclasses · Conferences**

> ⚠️ O título de "Conferences " no Notion tem **espaço no final**. Aplicar
> `.strip()` ao montar a cópia.

A lista sai do **banco**, não do MCP: a migration da ADR-0012 já vai adicionar
procedência em `documents`, e esta spec estende esse mesmo trabalho com a seção
(o ancestral de primeiro nível abaixo do root) de cada documento. A lista de
temas vira então `SELECT DISTINCT` sobre documentos ativos — sem round-trip MCP
no caminho da resposta.

Para o sync saber a seção, `_collect_scope` passa a propagar essa informação na
travessia: a pilha guarda `(page_id, secao)` em vez de só `page_id`. Filhos
diretos do root recebem o próprio título como seção; descendentes herdam a do
ancestral. `NotionPage` ganha o campo, o mapper leva até a Entity, e a Action de
ingestão persiste.

### 5. Cópia

**pt-BR (default):**

> Não encontrei informações sobre isso na base de conhecimento.
>
> Eu respondo sobre os produtos e programas do ecossistema — Mentorship,
> Bootcamps, Programs, Masterclasses e Conferences. Tente perguntar sobre um
> desses temas.

**Inglês:**

> I didn't find information about this in the knowledge base.
>
> I answer questions about the ecosystem's products and programs — Mentorship,
> Bootcamps, Programs, Masterclasses and Conferences. Try asking about one of
> those topics.

A lista de temas é interpolada a partir do banco; o restante é fixo. Idioma
escolhido por heurística de stopwords sobre a pergunta, com pt-BR como default
(o produto é pt-BR). A heurística é uma função pura, testável isoladamente.

### 6. Camada 2 — o caso ambíguo

O [system prompt](../../../src/support/agent/prompts.py) passa a conter o texto
exato da recusa, instruindo o modelo a emiti-lo **literalmente** quando o
contexto fornecido não sustentar a resposta. Assim "renovação do PSP" — que passa
do limiar mas cujo contexto é de Products, não de Ops — produz a mesma mensagem
que a recusa determinística, em vez de uma resposta inventada a partir de
conteúdo vagamente relacionado.

## Onde cada peça mora

| Peça | Lugar | Por quê |
|---|---|---|
| `RAG_MAX_DISTANCE` | `src/support/core/settings.py` | configuração |
| Filtro de distância | `DocumentChunkRepository.search_similar` | é uma decisão de query |
| Seção do documento | coluna em `documents` + Entity/Mapper | procedência do dado (ADR-0012) |
| Propagação da seção | `NotionClient._collect_scope` | quem conhece a árvore |
| Lista de temas (query) | `DocumentRepository` (`SELECT DISTINCT`) | leitura de dado persistido |
| Lista de temas (caso de uso) | `ListKnowledgeSectionsAction` em `src/domain/documents/actions/` | fronteira do subdomínio `documents` |
| Texto + escolha de idioma | Domain Service em `src/domain/conversations/services/` | regra de apresentação sem dono natural, pura e testável |
| Gatilho da recusa | `AnswerQuestionAction` | é o caso de uso |

A `AnswerQuestionAction` (contexto `conversations`) **não** fala com o
`DocumentRepository` direto: compõe com `ListKnowledgeSectionsAction` do contexto
`documents`, seguindo a regra de que Actions compõem Actions e cada subdomínio é
acessado pela sua própria fronteira. O Domain Service que monta a cópia recebe a
lista pronta e permanece puro (sem I/O), o que o torna testável sem banco.

Nenhuma pasta nova; nada muda no frontend nem no controller.

## Testes

**Unitários (sem banco):**

- heurística de idioma: pt, en, pergunta curta/ambígua → default pt-BR;
- montagem da cópia: interpola os temas, aplica `.strip()` em "Conferences ";
- `_collect_scope` propaga seção: filho direto recebe o próprio título,
  neto herda a do ancestral;
- Action: `retrieve=True` + knowledge vazio → stream de recusa;
- Action: **`retrieve=False` + knowledge vazio → segue para o motor** (a guarda);
- Action: `retrieve=True` + knowledge não-vazio → segue para o motor.

**Integração (banco):**

- `search_similar` corta o que está acima do limiar e mantém o que está abaixo;
- lista de temas ignora documentos soft-deleted.

**Verificação manual:** rodar as 16 perguntas da tabela de calibração e conferir,
por camada:

- as **7 de dentro** respondem normalmente;
- as **4 sem relação** e as **3 de Ops acima do corte** recebem a recusa
  determinística (camada 1);
- as **2 de Ops abaixo do corte** (renovação do PSP, onboarding de mentorado)
  chegam ao modelo e devem produzir a mesma mensagem por decisão dele (camada 2).
  Este é o único resultado não-determinístico do conjunto — se falhar, o ajuste é
  no prompt, não no limiar.

## Fora de escopo

- Mudar `RAG_TOP_K` ou a estratégia de chunking (ver `chunking-calibration`).
- Reintroduzir SOPs/Ops na base — decisão de 2026-07-28 foi Products-only.
- Multi-root na descoberta.
- Qualquer mudança no frontend.

## Riscos

- **Limiar mal calibrado corta pergunta boa.** Mitigado pela folga medida
  (0.532 vs 0.615) e por ser um setting ajustável sem deploy de código.
- **A calibração vale para a base atual (42 docs).** Se a KB crescer muito, os
  números merecem nova medição. O script usado aqui foi descartável; a
  implementação deve versioná-lo (comando `knowledge:calibrate`, ao lado dos
  demais em `src/app/console/commands/`) para que a medição seja repetível em vez
  de refeita à mão.
- **Acoplamento com a ADR-0012.** Esta spec não pode ser implementada antes da
  migration de procedência. A ordem correta é: ADR-0012 primeiro, esta depois.
