# ADR-0012 — Escopo da KB aplicado também na recuperação, não só na descoberta

## Status

Aceito — 2026-07-28.

## Resumo

- **Decisão:** cada documento passa a registrar o root sob o qual foi ingerido
  (`kb_root_page_id`), e a recuperação (RAG) filtra pelo root **atual** de
  `NOTION_KB_ROOT_PAGE_ID`. Acesso avulso por id (tool do agente) valida
  ancestralidade antes de devolver conteúdo.
- **Aplica-se quando:** mexer em escopo da KB, ingestão/sync, recuperação, ou
  em qualquer tool que leia o Notion por id.
- **Regra prática:** escopo é invariante de **leitura**, não só de ingestão.
  Documento cujo `kb_root_page_id` ≠ root atual não é recuperado nem citado,
  independente de sync. Trocar a env var vale na hora, fail-closed.

---

## Contexto

A ADR-0011 restringiu a KB ao subtree de `NOTION_KB_ROOT_PAGE_ID` e prometeu que
"nada fora do subtree do root é descoberto, ingerido **ou respondido**". Na
implementação, porém, o escopo ficou aplicado em **um único ponto**: a travessia
de descoberta em `NotionClient.list_approved_pages`. Isso deixou dois furos, os
dois observados em produção-dev em 2026-07-28:

1. **Corpus anterior servido em silêncio.** A base já tinha 562 documentos
   ingeridos pela descoberta antiga (busca plana no workspace). A mudança de
   escopo não tocou nesses registros: 520 deles ficaram `status=approved`,
   `deleted_at IS NULL`, com chunks intactos — e portanto recuperáveis. O
   oráculo respondeu normalmente a uma pergunta de SOP cujo documento vive em
   "Growth & Marketing", um irmão de "Products" no nível do workspace. A
   reconciliação existe (`SyncKnowledgeBaseAction` faz soft-delete do que saiu do
   escopo), mas só roda no sync full — até alguém rodá-lo, a garantia é apenas
   documental. Uma promessa de confidencialidade que depende de um job ter rodado
   não é uma garantia.

2. **Tool de leitura por id sem escopo.** `FetchNotionTool` chamava
   `NotionClient.get_page(page_id)` direto, sem checar ancestralidade e sem nem
   olhar `is_approved`. Como o id vem do modelo (via citação ou inferência), a
   tool lia qualquer página do workspace visível à integração — inclusive fora do
   root. A travessia de descoberta não protege esse caminho porque ele não passa
   por ela.

A raiz comum: **escopo modelado como filtro de ingestão, quando é invariante de
leitura.** Enquanto o dado persistido não souber a que escopo pertence, e a
consulta não souber qual é o escopo vigente, cada troca de root reabre a mesma
classe de bug.

## Decisão

Aplicar escopo em três camadas, com o dado carregando sua própria procedência:

1. **Persistir procedência.** `documents` ganha `kb_root_page_id` (id do root sob
   o qual o documento foi ingerido), gravado pela ingestão a partir de
   `settings.NOTION_KB_ROOT_PAGE_ID`. Armazenado normalizado (sem hífens,
   minúsculo) para não depender do formato do id.

2. **Filtrar na recuperação.** `DocumentChunkRepository.search_similar` passa a
   exigir `kb_root_page_id = root atual`, junto de `status=approved` e
   `deleted_at IS NULL`. Documento de outro root não é recuperado nem citado,
   mesmo que nenhum sync tenha rodado.

3. **Validar ancestralidade no acesso avulso.** Leitura por id usa
   `NotionClient.get_page_in_scope`, que sobe a cadeia de `parent` até o root
   (ou até `workspace`/`database_id`, que encerram a busca) e devolve `None`
   fora do escopo. `FetchNotionTool` traduz `None` em recusa.

A descoberta escopada da ADR-0011 continua sendo a primeira barreira, e
`KnowledgeCurationPolicy` a defesa contra linhas de banco/PII. Esta ADR não as
substitui — fecha os caminhos que passavam ao lado delas.

## Consequências

- **Fail-closed na troca de root.** Repontar `NOTION_KB_ROOT_PAGE_ID` deixa a KB
  respondendo *menos* imediatamente (nada do root antigo é servido) até o sync
  reingerir sob o novo root. É a direção correta para um invariante de
  confidencialidade: o modo de falha é recusar, não vazar.
- **Reconciliação deixa de ser a única linha de defesa.** O sync full continua
  necessário para limpar o que saiu do escopo, mas um atraso nele não implica
  mais em resposta fora do escopo.
- **Custo de MCP no acesso avulso.** `get_page_in_scope` gasta uma chamada por
  nível de ancestralidade. Aceitável: é uma tool sob demanda, não o caminho
  quente. O sync segue usando `get_page` (ids já vêm da travessia, logo em
  escopo) para não pagar esse custo por página.
- **Migration com backfill.** Documentos existentes não têm procedência
  conhecida. O backfill marca o root vigente **apenas** nos documentos que a
  travessia atual confirma em escopo; o resto fica `NULL` e, por não casar com o
  root atual, deixa de ser recuperado — o que é o comportamento desejado.

## Alternativas consideradas

- **Confiar só na reconciliação do sync full.** Zero custo de implementação, mas
  mantém a garantia dependente de um job ter rodado — exatamente a falha que
  originou esta ADR. Descartada.
- **Checar ancestralidade ao vivo em cada resultado de busca.** Correto por
  construção e sempre atual, mas custa N cadeias de chamadas MCP por pergunta,
  no caminho quente do streaming. Inviável para latência de chat. Descartada.
- **Persistir o caminho completo de ancestrais em vez de só o root.** Permitiria
  repontar o escopo para um nó mais fundo sem reingerir, e responder "está sob
  X?" para qualquer X. Mais dado para manter coerente a cada mudança de árvore
  no Notion, sem ganho para o caso de uso atual (um root por vez). Descartada
  por ora — retomar se o escopo passar a ser multi-root.
- **Coluna booleana `in_scope` em vez do id do root.** Não distingue "em escopo
  de qual root", então uma troca de env var exigiria recalcular tudo antes de
  qualquer consulta ser confiável. Descartada.
