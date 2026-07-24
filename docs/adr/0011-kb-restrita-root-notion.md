# ADR-0011 — Base de conhecimento restrita ao subtree de um root configurável do Notion

## Status

Aceito — 2026-07-24.

## Resumo

- **Decisão:** a KB do oráculo é EXCLUSIVAMENTE a subárvore de uma página-raiz
  configurável do Notion (`NOTION_KB_ROOT_PAGE_ID`, hoje o folder "Products");
  a descoberta de páginas é uma travessia descendente a partir desse root.
- **Aplica-se quando:** mexer em ingestão/sync da KB, curadoria, ou no escopo do
  que o oráculo pode responder.
- **Regra prática:** nada fora do subtree do root é descoberto, ingerido ou
  respondido. Sem root configurado, o sync **aborta** (não devolve lista vazia).

---

## Contexto

A regra inegociável nº 4 (nada confidencial) era aplicada por curadoria
**estrutural + denylist**: `KnowledgeCurationPolicy` deixava passar qualquer
página-documento (`parent = page/workspace`) e barrava linhas de banco. A
descoberta era uma busca plana no workspace inteiro (`API-post-search`), então
"aprovado" significava, na prática, *qualquer documento em qualquer folder* —
inclusive folders que a dona do produto não quer expor.

Uma busca plana só conhece o parent imediato de cada página, não sua
ancestralidade, então não consegue expressar "somente o folder Products".

## Decisão

Restringir a KB à subárvore de um único root configurável e trocar a descoberta
por uma travessia descendente (`API-get-block-children`) a partir dele. Blocos
`child_page` aprovados pela policy são coletados e recursados; `child_database`
e a subárvore de páginas rejeitadas não são visitados. `KnowledgeCurationPolicy`
permanece como defesa-em-profundidade. O root vem de `NOTION_KB_ROOT_PAGE_ID`;
sua ausência faz `list_approved_pages` lançar `KnowledgeBaseConfigError`, pois um
run completo de sync com lista vazia soft-deletaria toda a base.

## Consequências

- Garantia **estrutural**: folders fora do root nunca são lidos — mais forte que
  filtrar no fim.
- Re-apontar o escopo é trocar uma env var, sem deploy de código.
- Mais chamadas MCP (travessia) que a busca plana — aceitável para um job de sync.
- Páginas aninhadas dentro de blocos de layout (colunas/toggles) não são
  descidas (só `child_page`); revisitar se o folder passar a usar esse padrão.

## Alternativas consideradas

- **Busca plana + filtro por ancestralidade:** N chamadas extras por página e a
  busca ainda lê todos os folders no caminho. Descartada.
- **Allowlist de parents imediatos:** perde docs aninhados 2+ níveis. Descartada.
