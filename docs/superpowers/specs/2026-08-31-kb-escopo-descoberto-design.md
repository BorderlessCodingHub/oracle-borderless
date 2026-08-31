# Escopo da KB descoberto pelo MCP — a permissão do Notion vira a fronteira

Data: 2026-08-31
Origem: reunião "Yuri <> Duanne — Oráculo Borderless", 06/08/2026; decisão de
implementar em 31/08/2026.
Substitui, na questão do escopo: ADR-0011, ADR-0012 (metade de leitura), ADR-0014.

## Contexto

Na reunião de 06/08 o Yuri disse, depois de percorrer as páginas do workspace
decidindo uma a uma o que ficava e o que saía:

> "Já limitei o escopo pra você, então você pode puxar tudo que o MCP está
> entregando. Aí quando eu atualizar, eu te aviso."

A [spec da Fase 1](2026-08-11-mvp-lancamento-fase1-design.md) implementou isso
como **allowlist explícita** de roots em `NOTION_KB_ROOT_PAGE_IDS`, mantendo o
desenho *fail-closed* dos ADR-0011/0012/0014: escopo é configuração, e a
configuração é invariante de leitura, não só de ingestão. A própria spec
registrou que "o que ele liberou e o que ele descreveu não coincidem
exatamente" e deixou a allowlist final pendente de confirmação.

Essa pendência nunca fechou, e ela é estrutural, não um detalhe de operação: a
allowlist obriga uma ida e volta humana ("liberei mais uma pasta" → "atualiza a
env var" → deploy) toda vez que o Yuri mexe na curadoria. O
`DetectKbRootDriftAction` foi construído justamente para tornar essa divergência
visível — o que é a confissão de que ela existe por construção.

A decisão desta spec elimina a divergência em vez de reportá-la: **o escopo
passa a ser a superfície de permissão da integração do Notion**, descoberta a
cada sync. O que o Yuri compartilha é o que o oráculo lê. Não há segunda lista
para manter em sincronia, porque não há segunda lista.

## Decisão

Os roots da base deixam de vir de variável de ambiente e passam a ser **todas as
páginas de nível de workspace que a integração do Notion enxerga**, descobertas
via `API-post-search`. A travessia por subárvore, a curadoria e a reconciliação
continuam como estão.

## Fora de escopo

- **A `KnowledgeCurationPolicy` não muda.** Linha de banco (`data_source_id` /
  `database_id`) continua barrada, a denylist de títulos continua igual. "Tudo
  que o MCP entrega" nunca significou PII: a regra inegociável nº 4 é preservada
  por esta política, não pelo escopo de roots.
- **Busca web, `SYSTEM_PROMPT`, `RetrievalGate`.** Continuam como estão.
- **Autenticação.** Continua fora.
- **Chunking, embeddings, recuperação por distância.** Só o filtro de escopo sai
  das consultas; o resto do caminho de RAG é intocado.

---

## 1. Descoberta

`NotionClient.list_approved_pages()` deixa de ler `settings.kb_root_page_ids` e
passa a obter os roots de `list_workspace_root_pages()` — método que **já
existe** ([`notion_client.py`](../../../src/support/clients/notion/notion_client.py))
e hoje serve apenas ao relatório de drift. Ele pagina `API-post-search`
filtrando `parent.type == "workspace"` e devolve ids normalizados.

A partir dos roots, nada muda: `_collect_scope` desce a subárvore por
`child_page`, não visita `child_database`, aplica a `KnowledgeCurationPolicy`
antes de descer (uma página barrada não tem os filhos visitados), etiqueta
`section` e `kb_root_page_id`. Página alcançável por dois roots continua
registrada sob o primeiro que a alcançar — a ordem agora é a que o `search`
devolve, não a de declaração.

### Por que topo + subárvore, e não busca plana

O `search` do MCP devolve páginas de qualquer nível, e uma leitura literal de
"tudo" seria ingerir todas elas sem travessia. Foi descartado por dois motivos
concretos:

- **Perde `section`.** O ancestral de primeiro nível abaixo do root vai para
  `kb_section` e é usado na citação. Busca plana não tem de onde derivá-lo.
- **Perde a poda de subárvore da denylist.** Hoje, uma página cujo título casa a
  denylist impede a visita aos filhos. Com busca plana os filhos voltam sozinhos
  no resultado e entram. Era exatamente a descoberta que o ADR-0012 removeu, e
  removê-la de novo enfraqueceria a defesa em profundidade da regra nº 4.

Limitação aceita: se o Yuri compartilhar com a integração uma subpágina isolada
cujo pai **não** está compartilhado, ela não entra. O modelo mental dele na
reunião era o nível de topo ("pode deixar / vou tirar", página por página), e o
`knowledge:roots` (§6) torna o conjunto consumido inspecionável a qualquer
momento.

## 2. Recuperação: o filtro por root sai

Seis consultas filtram hoje `kb_root_page_id.in_(settings.kb_root_page_ids)`:

| Arquivo | Linhas |
|---|---|
| `src/domain/documents/repositories/document_repository.py` | 73, 105, 135 |
| `src/domain/documents/repositories/document_chunk_repository.py` | 30, 86, 113 |

O predicado de root sai das seis. `status == "approved"` e `deleted_at IS NULL`
permanecem em todas — a reconciliação continua sendo o que tira documento de
circulação. A guarda `if not roots: return []` some junto: ela existia porque
`IN ()` é SQL inválido e porque, sem roots, a leitura precisava degradar para
"sem conhecimento" em vez de expor tudo. Sem lista, não há o que guardar.

**Razão.** O filtro de leitura do ADR-0012 existia para compensar um escopo *de
configuração* que podia divergir do escopo *de permissão* — o incidente que o
motivou foi 520 documentos de um corpus antigo continuarem recuperáveis depois
que a env var mudou. Quando o escopo **é** a superfície de permissão, não há o
que divergir: só o Yuri estreita o escopo, e só despublicando no Notion.

A alternativa considerada foi persistir o conjunto descoberto numa tabela e
filtrar contra ela. Descartada: recuperaria a garantia apenas na janela que a
própria reconciliação fecha a cada sync, ao custo de uma migration, um
repositório e um modo de falha novo e pior — tabela vazia no bootstrap
filtraria tudo, e o oráculo subiria mudo.

**O que se perde, explicitamente:** despublicar uma página no Notion deixa de
ter efeito imediato. Ela continua recuperável e citável até o próximo sync
rodar. Antes, trocar a env var valia na hora. Risco aceito (§8).

## 3. Leitura por id: ancestralidade vira procedência

`get_page_in_scope()` sobe a cadeia de `parent` procurando um root da allowlist e
devolve `None` quando não acha. Dois chamadores dependem disso: a
[`FetchNotionTool`](../../../src/support/agent/tools.py) do agente e o comando
`knowledge:ingest`.

Sem allowlist, a pergunta "esta página está no escopo?" vira "a integração
consegue ler esta página?" — que o próprio MCP responde negando o acesso. Mas a
subida de `parent` **não** é deletada: ela deixa de ser checagem de autorização e
vira **derivação de procedência**. O método passa a subir até a página cujo
`parent.type` é `workspace` e devolve esse id como `kb_root_page_id`, sem nunca
recusar por ancestralidade. Renomeado para `get_page_with_provenance()`, porque
o nome antigo prometeria um escopo que ele não aplica mais.

Isso mantém `kb_root_page_id` preenchido e verdadeiro — o que sustenta tanto a
auto-cura de procedência do sync (§5) quanto a contagem por root do
`knowledge:roots` (§6) — sem que a coluna volte a gatilhar decisão de acesso.

**Buraco que isso abre e que esta spec fecha junto.** `FetchNotionTool.run` hoje
**ignora** `page.is_approved`: só verifica se o retorno é `None`. A tool nunca
serviu linha de banco por acidente — a subida de `parent` parava em `database_id`
e devolvia `None`. Trocando a recusa por ancestralidade sem mais nada, o agente
passaria a conseguir buscar uma linha de banco por id, isto é, PII direto no
contexto da resposta.

A tool e o `knowledge:ingest` passam a recusar quando `is_approved` for falso,
com a mesma mensagem de fora de escopo que a tool já emite. Isso deixa a proteção
**onde ela sempre deveria ter estado**: na `KnowledgeCurationPolicy`, e não como
efeito colateral de uma checagem de ancestralidade.

## 4. Fail-closed: o que resta

Um único freio permanece, e é categoricamente diferente de "um root a menos":

> **Zero roots descobertos → `KnowledgeBaseConfigError`; o sync aborta.**

Descoberta vazia não significa "o Yuri despublicou tudo": significa token
revogado, MCP fora do ar, ou `search` devolvendo vazio por erro. Reconciliar
isso soft-deletaria a base inteira numa única rodada. É o mesmo abort que existe
hoje, com a condição vindo da descoberta em vez da env var.

Fora esse caso, o sync **confia na descoberta**: se um root sumiu, suas páginas
saem de `approved_ids`, a reconciliação faz soft-delete e o `SyncReport` conta
as remoções. Sem snapshot, sem limiar, sem confirmação. Foi decisão explícita —
o custo de um soluço do Notion é uma reingestão com re-embedding no sync
seguinte, e a base é pequena.

## 5. Reconciliação

`SyncKnowledgeBaseAction` não muda. O comentário longo em torno de `left_scope`
descreve o mecanismo corretamente e continua válido: a única saída de escopo
observável é a página não ter aparecido na travessia da rodada. O que muda é
apenas a origem dos roots percorridos.

A auto-cura de procedência (reingerir quando `kb_root_page_id` gravado difere do
descoberto) também continua, e passa a cobrir um caso novo: página que muda de
root porque o Yuri a moveu entre pastas de topo.

## 6. Superfície de configuração e comandos

**Env vars.** `NOTION_KB_ROOT_PAGE_IDS` e `NOTION_KB_ROOT_PAGE_ID` deixam de ter
qualquer leitor de escopo e passam a ser **detectores de deploy defasado**:
`LifespanManager._validate_kb_root_env` levanta no boot se qualquer uma estiver
preenchida, com mensagem apontando que a KB agora é descoberta. É a extensão do
padrão que já existe hoje para o nome singular — um deploy velho falha alto em
vez de subir com um escopo que ninguém lê.

`Settings.kb_root_page_ids` é removida; os dois campos ficam como `str | None`
crus, lidos só pelo detector. O `.env.example` perde a lista de ids e ganha a
explicação de que o escopo vem do compartilhamento no Notion.

**`knowledge:roots`.** Deixa de reportar drift — allowlist e visibilidade viram
a mesma coisa por construção, e comparar um conjunto consigo mesmo não informa
nada. O comando passa a listar os roots em consumo (id e título) com a contagem
de documentos ingeridos sob cada um — o que exige um método de contagem por
`kb_root_page_id` no `DocumentRepository`. É o que responde "o oráculo está
mesmo lendo o que eu liberei?". `DetectKbRootDriftAction`, o DTO `KbRootDrift` e
o aviso de drift ao fim do `SyncKnowledgeBaseJob` são deletados.

**`knowledge:calibrate`.** A guarda `if not settings.kb_root_page_ids` e o
predicado `kb_root_page_id.in_(...)` na consulta saem; a calibração passa a
medir sobre a base inteira aprovada e não-deletada, coerente com o que a
recuperação faz.

**`database/seeds/dev_documents_seed.py`.** Hoje estampa o primeiro root da
allowlist para o documento de dev permanecer recuperável. Sem filtro de leitura,
a procedência deixa de afetar recuperação: o seed passa a estampar a constante
`"seed"`, que identifica a origem sem fingir uma página do Notion.

**`architectureMap.ts`.** As descrições das caixas de descoberta e de
recuperação mencionam "roots liberados" e "escopado aos roots"; passam a
descrever descoberta e recuperação sem escopo configurado. Nenhum arquivo
declarado no mapa deixa de existir, então o `architectureMap.test.ts` continua
verde — mas a atualização vai no mesmo commit, conforme CLAUDE.md.

## 7. ADR-0015

A decisão contraria três ADRs aceitos e precisa de registro próprio antes da
implementação: **ADR-0015 — Escopo da KB descoberto pela permissão do Notion**,
substituindo ADR-0011 e ADR-0014 integralmente e a metade de leitura do
ADR-0012. Segue o template do `docs/adr/README.md`, com `## Resumo` no topo.

A metade do ADR-0012 que **sobrevive** e precisa ficar explícita no texto: o
caminho de leitura por id continua sendo um ponto de aplicação de política — o
que mudou é qual política ele aplica (curadoria, não ancestralidade).

## 8. Riscos aceitos

| Risco | Mitigação | Aceito porque |
|---|---|---|
| Página despublicada continua recuperável até o próximo sync | Cadência do `SyncKnowledgeBaseJob` | O escopo agora é a permissão; despublicar é ação deliberada e rara, e a janela é de uma cadência de job |
| Soluço do `search` remove documentos legítimos | Sync seguinte reingere | Base pequena; custo é re-embedding, não perda de dado |
| Yuri compartilha algo indevido por engano | `KnowledgeCurationPolicy` barra linha de banco e títulos da denylist; `knowledge:roots` torna o conjunto inspecionável | O compartilhamento é a fronteira que ele mesmo pediu para ser a fronteira |
| Subpágina compartilhada isoladamente não entra | `knowledge:roots` mostra o que está sendo consumido | Não corresponde ao modelo de curadoria dele; se ocorrer, vira spec própria |

## 9. Testes

Os testes de escopo existentes afirmam a garantia que está sendo removida. São
**reescritos** para a garantia nova, não deletados:

| Arquivo | Vira |
|---|---|
| `tests/unit/support/clients/notion/test_notion_client_scope.py` | Descoberta a partir de `list_workspace_root_pages`; `child_database` não visitado; página barrada pela denylist não tem filhos visitados; zero roots → `KnowledgeBaseConfigError` |
| `tests/unit/support/clients/notion/test_notion_client_ancestry.py` | `get_page_with_provenance` sobe até a página de topo e a estampa; nunca recusa por ancestralidade; linha de banco volta reprovada pela curadoria |
| `tests/unit/support/agent/test_tools_scope.py` | `FetchNotionTool` recusa página reprovada pela curadoria (era: recusa por fora do root) |
| `tests/unit/app/console/test_knowledge_ingest_command.py` | Procedência vem da subida de `parent`; página reprovada pela curadoria não é ingerida |
| `tests/integration/domain/documents/test_chunk_repository_scope_filter.py` | Recuperação devolve documento independentemente de `kb_root_page_id`; documento soft-deletado continua excluído |
| `tests/unit/support/core/test_settings_kb_root.py` | Deletado — a propriedade `kb_root_page_ids` deixa de existir |
| `tests/unit/support/core/test_lifespan.py` | Boot falha com qualquer das duas env vars preenchidas |
| `tests/unit/domain/documents/actions/test_sync_knowledge_base_action.py` | Roots vindos da descoberta; root ausente na rodada → soft-delete |
| `tests/unit/domain/documents/actions/test_detect_kb_root_drift_action.py` | Deletado com a Action |

A reescrita de `test_tools_scope.py` é a mais importante da lista: é a regressão
que o §3 fecha, e sem cobertura ela volta silenciosa.

## 10. Corte em produção

1. Deploy com a descoberta e sem o filtro de leitura.
2. Imediatamente: `python cli.py knowledge:sync`.

Entre os dois passos, documentos ingeridos sob escopos anteriores e ainda não
soft-deletados ficam recuperáveis — era o filtro de leitura que os escondia. Sem
usuários no produto, a janela é aceitável; ela não é zero e não deve ser
descrita como tal.

O sync incremental (sem `--force`) já basta: página nunca vista entra por
`current is None`, documento soft-deletado que volta ao escopo entra por
`deleted_at`, página que trocou de root entra pela auto-cura de divergência de
procedência, e a reconciliação de saída de escopo roda em qualquer sync não
parcial, independente de `--force`. O `--force` reingeriria a base inteira,
inclusive as páginas inalteradas — custo de embeddings proporcional ao
tamanho da base inteira, sem ganho correspondente.

O sync do corte também **não pode usar `--limit`**: em `SyncKnowledgeBaseAction`,
`partial = limit is not None` desliga a reconciliação inteira, e é a
reconciliação que fecha a janela descrita acima. Um `--limit` aqui deixaria
documentos de escopos anteriores recuperáveis indefinidamente, não só durante
a janela entre deploy e sync.

## 11. Critérios de aceite

- Uma pergunta sobre um documento de uma página de topo que **nunca** esteve na
  allowlist (ex.: `Borderless Coding Labs`) é respondida com citação da fonte
  correta, sem nenhuma mudança de configuração.
- Nenhuma env var de root é lida para decidir escopo; com qualquer uma delas
  preenchida, a aplicação não sobe.
- `fetch_notion_page` sobre o id de uma linha de banco devolve a recusa de fora
  de escopo.
- Descoberta vazia aborta o sync sem remover documento nenhum.
- `knowledge:roots` lista os roots em consumo com a contagem por root.
- `pytest` verde, `prospector` limpo, `alembic check` limpo (esta spec não tem
  migration), build do frontend passa.

## 12. Pendências

- Avisar o Yuri de que o aviso manual ("te aviso quando liberar mais coisa")
  deixa de ser necessário: compartilhar com a integração passa a bastar, e o
  efeito aparece no sync seguinte.
