# ADR-0014 — KB é a união dos subtrees de múltiplos roots do Notion

## Status

Aceito — 2026-08-11. Substitui o [ADR-0011](0011-kb-restrita-root-notion.md).

## Resumo

- **Decisão:** a KB é a união dos subtrees de `NOTION_KB_ROOT_PAGE_IDS`. Cada
  documento registra o root sob o qual foi descoberto; recuperação e acesso
  por id validam pertencimento ao conjunto.
- **Aplica-se quando:** mexer em escopo da KB, ingestão/sync, recuperação, ou
  em qualquer tool que leia o Notion por id.
- **Regra prática:** escopo continua invariante de leitura. Documento cujo
  `kb_root_page_id` não está entre os roots atuais não é recuperado nem
  citado. Lista vazia é fail-closed.

---

## Contexto

O ADR-0011 restringiu a KB ao subtree de uma única página-raiz porque, na
época, a KB era o folder "Products": um nó do Notion com todo o conteúdo
liberado por baixo dele, e nada liberado fora. Um root único bastava para
expressar esse escopo, e a travessia descendente a partir dele era a garantia
estrutural.

Na reunião de 06/08 a curadoria passou para o lado do Notion: quem decide o
que é liberado não é mais "está dentro do folder Products", é uma seleção
direta de páginas feita por quem cura o conteúdo. As páginas liberadas
resultantes são **irmãs no nível do workspace** — não existe ancestral comum
entre elas que não seja o workspace inteiro. Um root único não consegue
expressar esse escopo: ou ele sobe até o workspace (perdendo toda a garantia
estrutural do ADR-0011, porque tudo fica "dentro do root") ou fica preso a um
único ramo (excluindo páginas liberadas que vivem em outro).

O ADR-0012 continua valendo — escopo é invariante de leitura, não só de
descoberta — mas sua regra prática foi escrita em termos de comparação com
**um** root (`kb_root_page_id ≠ root atual`). Esta ADR emenda essa regra: a
comparação agora é `kb_root_page_id ∉ roots atuais`. Nenhuma das três camadas
que o ADR-0012 estabeleceu (persistir procedência, filtrar na recuperação,
validar ancestralidade no acesso avulso) muda de forma — só o "root" singular
vira "conjunto de roots".

## Decisão

Trocar `NOTION_KB_ROOT_PAGE_ID` (um id) por `NOTION_KB_ROOT_PAGE_IDS` (CSV de
ids) e propagar "root" → "conjunto de roots" pelas mesmas três camadas do
ADR-0012:

1. **Configuração.** `settings.kb_root_page_ids` faz o parsing do CSV:
   normaliza cada id, remove duplicatas, preserva a ordem de declaração, e
   ignora entradas comentadas (`#`). Lista vazia é fail-closed — os
   chamadores tratam isso como "sem escopo configurado", nunca como "sem
   filtro" (o mesmo comportamento do ADR-0011 para o caso de um único root
   ausente, agora generalizado).

2. **Descoberta.** A travessia percorre cada root da lista e **etiqueta cada
   página descoberta com o root sob o qual foi encontrada**
   (`kb_root_page_id`). Uma página alcançável por mais de um root (subtrees
   podem se sobrepor) fica etiquetada com o **primeiro root da ordem de
   declaração** que a alcança — a travessia é determinística porque a ordem
   de `NOTION_KB_ROOT_PAGE_IDS` é fixa.

3. **Acesso avulso por id.** `NotionClient.get_page_in_scope` sobe a
   ancestralidade da página pedida e aceita quando **algum** ancestral bate
   com **algum** root da lista, devolvendo qual root casou (para gravar a
   mesma procedência que a descoberta gravaria).

4. **Recuperação.** As consultas que antes filtravam por
   `kb_root_page_id == root atual` passam a filtrar por
   `kb_root_page_id.in_(roots atuais)`, nas seis consultas do caminho de
   busca/citação. `NULL` nunca casa com `IN`, então documento sem procedência
   continua invisível — o mesmo comportamento fail-closed do ADR-0012, sem
   caso especial para lista vazia.

5. **Reconciliação do sync.** Página sai de escopo por dois critérios: ficou
   ausente da travessia atual, ou sua procedência ficou fora da allowlist
   vigente. A comparação usa a procedência **da travessia atual** (o root que
   cada página tem *agora*, dada a ordem de declaração vigente), não o
   snapshot gravado antes da ingestão — reordenar a lista de roots pode
   trocar a procedência etiquetada de uma página sem mudar se ela está ou não
   em escopo.

6. **Sinal de drift.** O comando `knowledge:roots` e um `WARNING` no
   `SyncKnowledgeBaseJob` comparam a allowlist configurada contra o que a
   integração do Notion efetivamente alcança, e apontam divergência
   explicitamente. Isso substitui o aviso humano ("te aviso quando liberar
   mais coisa") por um sinal que o operador consulta ou recebe no log — a
   allowlist pode ficar defasada da liberação real sem que ninguém precise
   lembrar de avisar.

Nenhuma migration foi necessária: `documents.kb_root_page_id` já guardava o
id de um root desde o ADR-0012; multi-root só muda o universo de valores
válidos contra o qual ele é comparado, não o shape do dado.

## Consequências

- **A env var singular deixa de existir.** `NOTION_KB_ROOT_PAGE_ID` não é lida
  em lugar nenhum do código corrente; quem reconfigurar precisa migrar para
  `NOTION_KB_ROOT_PAGE_IDS`.
- **Atribuição de root é posicional, não semântica.** Página alcançável por
  dois roots fica sob o primeiro da ordem de declaração — reordenar
  `NOTION_KB_ROOT_PAGE_IDS` pode reatribuir procedência de páginas na
  sobreposição sem que nenhum conteúdo mude no Notion. É previsível (a ordem
  é a fonte da verdade), mas não é óbvio de fora; documentar a ordem
  declarada é parte de operar a allowlist.
- **Drift vira sinal explícito, não convenção verbal.** `knowledge:roots` e o
  `WARNING` no sync existem porque, sem um root único e um dono claro do
  scope, é fácil a allowlist ficar defasada da liberação real do Notion sem
  ninguém notar — o problema que motivou o ADR-0012 (corpus antigo servido em
  silêncio) tende a se repetir com mais superfície quando há vários roots
  para perder de vista.
- **Custo de MCP no acesso avulso cresce com o número de roots.**
  `get_page_in_scope` testa a ancestralidade contra cada root até achar (ou
  esgotar) — pior caso linear no tamanho da lista. Aceitável pelo mesmo motivo
  do ADR-0012: é tool sob demanda, não o caminho quente do sync.
- Documentos ingeridos por um sync anterior a esta ADR mantêm o
  `kb_root_page_id` do root único que existia então; continuam recuperáveis
  normalmente porque esse id, sendo um `NOTION_KB_ROOT_PAGE_ID` válido do
  passado, tipicamente permanece um dos ids em `NOTION_KB_ROOT_PAGE_IDS` — não
  há backfill necessário para o caso comum de "root único virou o primeiro de
  vários".

## Alternativas consideradas

- **Um root sintético no workspace, sob o qual mover/agrupar as páginas
  liberadas.** Preservaria a garantia estrutural de root único, mas exige
  reestruturar o Notion para servir a curadoria do lado da engenharia — na
  contramão de a curadoria ter passado para o lado do Notion. Descartada.
- **Allowlist de páginas individuais (sem noção de subtree/root).** Mais
  direta para o caso "curadoria seleciona páginas soltas", mas perde a
  travessia descendente: cada página nova sob uma já liberada exigiria
  reconfigurar a allowlist, em vez de herdar aprovação por estar no subtree.
  Descartada — o ADR-0011 já tinha resolvido esse problema para o caso de um
  root; multi-root generaliza a solução em vez de abandoná-la.
- **Coluna de procedência como lista de roots por documento (todos os roots
  que alcançam a página), em vez de um único root etiquetado.** Evitaria a
  atribuição posicional na sobreposição, mas complica a comparação de
  recuperação (de igualdade/`IN` para intersecção de conjuntos em cada linha)
  para um caso — sobreposição de subtrees — que hoje é raro na curadoria
  real. Descartada por ora; revisitar se sobreposição se tornar comum.
