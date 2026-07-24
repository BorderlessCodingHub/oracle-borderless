# Design — Restringir a base de conhecimento ao folder "Products" do Notion

**Data:** 2026-07-24
**Status:** aprovado (aguardando plano de implementação)

## Problema

Hoje o oráculo pode consumir **qualquer página-documento de qualquer folder** do
workspace do Notion. A curadoria atual ([knowledge_curation_policy.py](../../../src/domain/documents/services/knowledge_curation_policy.py))
filtra apenas por **tipo estrutural** (página-documento vs. linha de banco) e por
uma denylist de títulos — mas não tem noção de *localização na árvore*.

A dona do produto quer que **apenas o folder "Products"** vire base de
conhecimento. Os demais folders (incluindo os privados) **não devem ser
ingeridos nem tratados como consumíveis** — devem ser tão inacessíveis quanto os
folders privados.

## Por que o mecanismo atual não expressa isso

`NotionClient.list_approved_pages()` faz uma **busca plana no workspace inteiro**
(`_search_all` → `API-post-search` com query vazia) e depois filtra cada
resultado por tipo + título. Uma busca plana:

- enxerga o workspace todo (inclusive folders privados/outros), e
- só conhece o **parent imediato** de cada página, não sua ancestralidade.

Logo, "esta página está dentro de Products?" é uma pergunta que o desenho atual
**não consegue responder**. O conceito de "aprovado" hoje é *"qualquer
página-documento em qualquer lugar"* — exatamente o que se quer eliminar.

## Estrutura do Notion (verificada via MCP em 2026-07-24)

- **"Products"** é uma página de topo (`parent.type = workspace`), id
  `23d8d655-c889-806d-8828-d527ce6a1529`, ícone 👨🏼‍🚀. Funciona como folder.
- Filhos diretos (blocos `child_page`): **Mentorship, Bootcamps, Programs,
  Masterclasses, Conferences** — cada um com sua própria subárvore.

Ou seja: "o folder Products" = **subárvore descendente da página raiz
`23d8d655-c889-806d-8828-d527ce6a1529`**.

## Decisão

**Abordagem A — travessia DESCENDENTE a partir de um root configurável.**

Trocar a descoberta de páginas: em vez de busca plana no workspace, caminhar a
árvore para baixo a partir da página raiz de Products. Tudo que é descoberto
está, **por construção**, dentro de Products; qualquer coisa em outros folders
(ou privados) **nunca é visitada**, logo não pode ser ingerida nem respondida.

É uma garantia **estrutural**, alinhada à filosofia da regra inegociável nº 4
(*curadoria estrutural*, não blocklist).

### Alternativas descartadas

- **B — busca plana + filtro por ancestralidade.** Para cada hit, subir a cadeia
  de parents até o workspace e manter só os que passam por Products. Descartada:
  N chamadas extras por página e a busca ainda *lê* todos os folders privados no
  caminho — frágil e caro.
- **C — allowlist de parents imediatos.** Manter só páginas cujo parent direto é
  Products ou um de seus filhos diretos. Descartada: perde docs aninhados 2+
  níveis; quebra conforme a árvore cresce.

## Componentes e mudanças

### 1. Settings — ponteiro novo
Em [settings.py](../../../src/support/core/settings.py), no bloco do Notion:

```python
NOTION_KB_ROOT_PAGE_ID: str | None = None  # root do folder Products; KB = só o subtree dele
```

Valor em `.env`: `23d8d655-c889-806d-8828-d527ce6a1529`.

### 2. NotionClient — travessia da árvore no lugar da busca plana
Em [notion_client.py](../../../src/support/clients/notion/notion_client.py),
`list_approved_pages()` deixa de chamar `_search_all` e passa a caminhar para
baixo a partir do root:

- `API-get-block-children` no root → para cada bloco `child_page`: é uma página
  candidata (montar `NotionPageRef(object_type="page", parent_type="page_id",
  title=<child_page.title>)`), passar pela `KnowledgeCurationPolicy`, e
  **recursar** nela para sub-páginas mais profundas.
- Blocos `child_database` são **pulados e não recursados** (é onde vivem
  linhas de banco / PII) — coerente com a regra nº 4.
- Metadados (`title`, `last_edited_time`) vêm direto do bloco, mesmo formato que
  `list_approved_pages` já devolve. A própria página-índice "Products" **não** é
  ingerida (só seus descendentes).

**Fail-loud em má configuração:** se `NOTION_KB_ROOT_PAGE_ID` estiver ausente,
`list_approved_pages` **lança** um erro de configuração em vez de devolver `[]`.
Isso é crítico: [sync_knowledge_base_action.py](../../../src/domain/documents/actions/sync_knowledge_base_action.py)
(reconciliação, ~linhas 84-90) faz *soft-delete* de todo documento fora da lista
aprovada num run completo — uma lista vazia **apagaria a base inteira**. Lançar
aborta o sync antes do reconcile destrutivo, deixando a KB intacta.

### 3. KnowledgeCurationPolicy — inalterada, rebaixada a defesa-em-profundidade
A policy continua idêntica (rejeita linha de banco, denylist de títulos). Seu
papel muda: o escopo agora é primariamente estrutural (a travessia), e a policy
é a segunda linha de defesa. Sem mudança de código; os 11 testes atuais seguem
verdes.

### 4. `get_page()` — inalterada
Fetch de página única usado na ingestão; os ids agora só vêm da travessia
escopada, então não precisa mudar.

### 5. ADR (leve)
Adicionar ADR curto — *"Base de conhecimento restrita ao subtree de um root
configurável do Notion"* — refinando como a regra nº 4 é aplicada. Não contradiz
nenhum ADR existente.

## Testes

- **Novo:** teste de travessia de `list_approved_pages` injetando um `call` MCP
  fake (root → child_pages + um child_page aninhado + um child_database) e
  afirmando que só páginas em escopo voltam e que o ramo de banco é pulado; mais
  um teste de que root ausente lança.
- **Inalterados:** testes da policy; testes da sync-action (usam
  `FakeNotionClient`, não afetados).

## Fora de escopo (YAGNI)

- Verificar em `get_page()` que a página pertence ao subtree (defesa-em-
  profundidade redundante — os ids já vêm escopados).
- Suportar múltiplos roots. Hoje é um só (Products); generalizar só quando
  houver segundo folder de conhecimento.
