# ADR-0015 — Escopo da KB descoberto pela permissão do Notion

## Status

Aceito — 2026-08-31. Substitui o [ADR-0011](0011-kb-restrita-root-notion.md) e o
[ADR-0014](0014-kb-multi-root.md); substitui a metade de leitura do
[ADR-0012](0012-escopo-kb-aplicado-na-recuperacao.md).

## Resumo

- **Decisão:** os roots da KB deixam de vir de variável de ambiente e passam a
  ser todas as páginas de nível de workspace que a integração do Notion
  enxerga, descobertas a cada sync via `API-post-search`. O filtro de escopo
  sai da recuperação; a leitura por id recusa por curadoria, não por
  ancestralidade.
- **Aplica-se quando:** mexer em escopo da KB, ingestão/sync, recuperação, ou
  em qualquer caminho que leia o Notion por id.
- **Regra prática:** o que a integração enxerga é o escopo. Não existe segunda
  lista para manter em sincronia. Quem decide se uma página é ingerível é a
  `KnowledgeCurationPolicy` — e ela precisa ser checada explicitamente em todo
  caminho de leitura por id.

---

## Contexto

O ADR-0014 implementou o pedido da reunião de 06/08 ("já limitei o escopo pra
você, pode puxar tudo que o MCP está entregando") como allowlist explícita de
roots em `NOTION_KB_ROOT_PAGE_IDS`. A [spec da Fase 1](../superpowers/specs/2026-08-11-mvp-lancamento-fase1-design.md)
registrou, na própria época, que "o que ele liberou e o que ele descreveu não
coincidem exatamente" e deixou a allowlist final pendente de confirmação.

A pendência é estrutural, não operacional. A allowlist obriga uma ida e volta
humana — o Yuri libera uma pasta, avisa, alguém edita a env var, alguém faz
deploy — toda vez que a curadoria muda. O `DetectKbRootDriftAction` foi
construído para tornar essa divergência visível, o que é a confissão de que ela
existe por construção: duas listas descrevendo a mesma intenção sempre
divergem.

## Decisão

O escopo da KB é a superfície de permissão da integração do Notion. Os roots
são descobertos a cada sync; a travessia por subárvore, a curadoria e a
reconciliação não mudam.

Três consequências diretas:

1. **Recuperação sem filtro de root.** O filtro de leitura do ADR-0012 existia
   para compensar um escopo *de configuração* que podia divergir do escopo *de
   permissão*. Quando o escopo é a permissão, não há o que divergir.
2. **Leitura por id recusa por curadoria.** A subida de `parent` deixa de
   autorizar e passa a derivar procedência (`kb_root_page_id`). A recusa que
   ela fazia por acidente — linha de banco tem `parent.type == "database_id"` e
   devolvia `None` — passa a ser feita explicitamente pela
   `KnowledgeCurationPolicy`.
3. **Fail-closed só na descoberta vazia.** Zero páginas de topo visíveis não
   significa "o Yuri despublicou tudo": significa token revogado ou MCP fora do
   ar. O sync aborta em vez de reconciliar, porque reconciliar apagaria a base
   inteira numa rodada.

## Consequências

**Positivas.** Uma lista a menos para manter em sincronia; liberar conteúdo
passa a ser ação única do lado do Notion, com efeito no sync seguinte; a
proteção contra PII fica num lugar só e explícito, em vez de depender de um
efeito colateral da travessia de ancestralidade.

**Negativas, aceitas.** Despublicar uma página deixa de ter efeito imediato: ela
continua recuperável e citável até o próximo sync rodar — antes, trocar a env
var valia na hora. E o time perde o freio de configuração: não há mais como
excluir uma página do lado do código sem pedir ao Notion.

**Neutra.** `kb_root_page_id` continua preenchida e verdadeira, mas deixa de
gatilhar decisão de acesso: vira procedência para diagnóstico
(`knowledge:roots`) e para a auto-cura do sync.

## Alternativas consideradas

**Persistir o conjunto descoberto numa tabela e continuar filtrando a
recuperação contra ela.** Recuperaria a garantia de leitura apenas na janela
que a própria reconciliação já fecha a cada sync, ao custo de uma migration, um
repositório e um modo de falha novo e pior: tabela vazia no bootstrap filtraria
tudo, e o oráculo subiria mudo sem nada ligar o sintoma à causa.

**Busca plana: ingerir toda página que o `search` devolve, em qualquer nível.**
É a leitura literal de "tudo", e foi a descoberta original que o ADR-0012
removeu. Perde `kb_section` (usada na citação) e perde a poda de subárvore da
denylist — hoje uma página barrada impede a visita aos filhos; com busca plana
os filhos voltam sozinhos no resultado e entram. Enfraqueceria a defesa em
profundidade da regra nº 4 em troca de cobrir um caso (subpágina compartilhada
isoladamente, com o pai não compartilhado) que não corresponde ao modelo de
curadoria em uso.
