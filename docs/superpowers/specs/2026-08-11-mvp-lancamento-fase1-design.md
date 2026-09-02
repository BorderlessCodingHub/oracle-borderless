# MVP de lançamento — Fase 1: escopo multi-root da KB e home como chat

Data: 2026-08-11
Origem: reunião "Yuri <> Duanne — Oráculo Borderless", 06/08/2026.

## Contexto

A reunião de 06/08 fechou o caminho até o lançamento do oráculo para o
ecossistema. Seis frentes saíram de lá, com a ordem definida pelos próprios
participantes: refatorar o escopo da base de conhecimento, simplificar a
interface, abrir o escopo de resposta com busca web, subir em
`oracle.<domínio>.com`, manter a página de ops e resolver autenticação por
último.

Duas decisões da reunião mudam premissas registradas em ADR:

1. **O escopo da KB deixa de ser um folder.** Yuri passou a curar o Notion do
   lado dele — liberando intencionalmente para a integração o que o oráculo pode
   ler — e pediu que a ingestão consuma tudo que o MCP entrega. As páginas
   liberadas são **irmãs no nível do workspace**, sem ancestral comum, o que
   torna impossível atender ao pedido trocando o valor de
   `NOTION_KB_ROOT_PAGE_ID` (ADR-0011).
2. **A interface deixa de ter landing.** O produto não será vendido; só o
   ecossistema tem acesso. A home passa a ser o chat.

## Roadmap

| Fase | Conteúdo | Estado |
|---|---|---|
| **1a** | Escopo multi-root da KB + relatório de drift | esta spec |
| **1b** | Home vira o chat; landing, Sobre e Base de conhecimento deletadas | esta spec |
| **1c** | Deploy em `oracle.<domínio>.com` | esta spec (investigação) |
| 2 | Abertura do escopo de resposta com busca web ancorada no ecossistema | spec própria |
| 3 | Autenticação da Borderless; `/ops` vira super admin de verdade | spec própria |

1a e 1b são independentes e podem ser implementadas em paralelo. 1c começa por
investigação e não bloqueia as outras duas.

## Fora de escopo

- **Busca web e abertura do escopo de resposta.** O `SYSTEM_PROMPT`, o
  `RetrievalGate` e a `WebSearchTool` ficam como estão. A tool já existe e
  continua explicitamente proibida de servir como fallback para lacunas da base.
- **Autenticação.** `useCurrentUser` segue devolvendo `isAdmin: true` fixo.
- **Assinatura, cobrança, multi-tenant.** A visão de subscription discutida na
  reunião não tem nada a implementar agora.

---

## Fase 1a — Escopo multi-root da KB

### Princípio

A forma da garantia não muda. Escopo continua sendo invariante de **leitura**,
não só de ingestão (ADR-0012); continua *fail-closed*; continua verificado na
recuperação e no acesso avulso por id. A única generalização é `root` → `roots`.

### Configuração

`NOTION_KB_ROOT_PAGE_IDS` (lista separada por vírgula) substitui
`NOTION_KB_ROOT_PAGE_ID` em `src/support/core/settings.py`. `Settings` expõe
`kb_root_page_ids`, que devolve os ids **normalizados** (sem hífen, via
`normalize_page_id`), deduplicados, preservando a ordem de declaração.

Lista vazia ou ausente continua lançando `KnowledgeBaseConfigError` em
`list_approved_pages`. A razão é a mesma do ADR-0011: um sync full com lista de
páginas vazia soft-deletaria a base inteira.

### Allowlist inicial

As páginas de nível de workspace hoje visíveis à integração:

| Página | Citada na reunião | Entra? |
|---|---|---|
| `Products` | sim, como fonte principal | sim |
| `Domínios & Subdomínios` | sim | sim |
| `Código de Cultura` | sim | sim |
| `Mapa Global de Papéis` | sim | sim |
| `Calendar 2026` | sim, de passagem | sim |
| `Borderless Coding Labs` | **não** | a confirmar |
| `Borderless Copy Bible` | **não** | a confirmar |

As duas últimas estão compartilhadas com a integração mas não foram mencionadas
na conversa. "Guerrilha", "Infraestrutura e Automação" e "Website", que Yuri
citou em voz alta, não aparecem no nível do workspace. **O que ele liberou e o
que ele descreveu não coincidem exatamente** — a allowlist final precisa ser
confirmada com ele antes de virar variável de ambiente. Até a confirmação, a
implementação usa as cinco linhas inequívocas.

### Descoberta

`NotionClient.list_approved_pages` percorre cada root da lista com a mesma
travessia descendente de hoje (`API-get-block-children`, blocos `child_page`
aprovados pela `KnowledgeCurationPolicy`, `child_database` não visitado).

A mudança estrutural: **cada página descoberta é etiquetada com o root sob o
qual foi encontrada**. Hoje o root chega separado até
`NotionPageMapper.to_entity(..., root_page_id=...)`, o que só funciona porque
existe um único root; com vários, a procedência precisa viajar junto da página,
caso contrário `kb_root_page_id` vira chute.

Uma página alcançável a partir de dois roots é registrada sob o primeiro root
que a alcançar, seguindo a ordem de declaração da lista. Isso mantém
`kb_root_page_id` como um valor único por documento e torna a atribuição
determinística.

### Ancestralidade

O caminho de leitura por id (`FetchNotionTool` → `NotionClient`) sobe a cadeia
de `parent` e aceita a página quando **algum** ancestral pertence à lista de
roots. É a lógica atual com `in` no lugar de `==`.

### Recuperação

Seis consultas trocam a comparação de escopo por pertencimento a conjunto:

- `src/domain/documents/repositories/document_repository.py` (linhas 74, 105, 135)
- `src/domain/documents/repositories/document_chunk_repository.py` (linhas 31, 86, 113)

`kb_root_page_id == root` passa a `kb_root_page_id.in_(roots)`. Isso preserva de
graça o comportamento que os testes de escopo já documentam: `NULL` nunca casa
com `IN`, logo documento sem procedência continua invisível à recuperação, sem
precisar de cláusula extra.

Também consomem a configuração e passam a ler a lista:
`SyncKnowledgeBaseAction`, `KnowledgeIngestCommand`, `KnowledgeCalibrateCommand`
e `database/seeds/dev_documents_seed.py`.

### Reconciliação

`SyncKnowledgeBaseAction` continua fazendo soft-delete do que saiu do escopo,
agora com dois critérios: documento cuja página não apareceu na união das
travessias, e documento cujo `kb_root_page_id` não pertence mais à lista de
roots vigente (caso de root removido da allowlist).

### Relatório de drift

Substitui o "te aviso no WhatsApp" combinado na reunião por um sinal no sistema.

**Comando `knowledge:roots`** (`src/app/console/commands/`): lista as páginas de
nível de workspace visíveis à integração, cruza com a allowlist e reporta os
dois lados da diferença:

- *visível mas fora da allowlist* — Yuri liberou algo e não avisou;
- *na allowlist mas invisível* — permissão revogada, página movida, ou id errado.

**Aviso automático:** `SyncKnowledgeBaseJob` emite um WARNING no log quando
detecta o primeiro caso. O sinal aparece sozinho, sem depender de alguém lembrar
de rodar o comando.

O comando não altera a allowlist. Incluir um root novo continua sendo decisão
humana, feita na variável de ambiente.

### Dados

Nenhuma migration. A coluna `kb_root_page_id` permanece como está. Os documentos
já ingeridos têm `kb_root_page_id` = root de `Products`, que continua na lista;
seguem válidos e recuperáveis. O próximo sync full apenas acrescenta os
documentos dos roots novos.

### ADR

ADR-0014, substituindo o ADR-0011 e emendando a regra prática do ADR-0012
(`kb_root_page_id` diferente do root atual → **não pertencente** ao conjunto de
roots atuais). ADRs são imutáveis: é documento novo, não edição dos anteriores.

### Testes

- `Settings.kb_root_page_ids`: CSV com espaços, ids com e sem hífen, duplicados,
  string vazia, variável ausente.
- Descoberta multi-root: páginas de dois roots distintos aparecem com o
  `kb_root_page_id` correto de cada um; página alcançável por dois roots recebe
  o primeiro da ordem; lista vazia lança `KnowledgeBaseConfigError`.
- Ancestralidade: página sob o segundo root é aceita; página fora de todos os
  roots é rejeitada; lista vazia rejeita tudo.
- Recuperação: documento de root fora da lista não é recuperado nem citado;
  documento com `kb_root_page_id` nulo não é recuperado (o teste que hoje
  protege contra a armadilha do `IS NULL` continua valendo).
- Reconciliação: root removido da allowlist faz soft-delete dos seus documentos.
- Drift: allowlist e visibilidade divergentes produzem as duas listas corretas.

Os onze arquivos de teste que hoje fazem `monkeypatch` de
`NOTION_KB_ROOT_PAGE_ID` migram para a variável plural.

### Mapa de arquitetura

`frontend/src/features/ops/architectureMap.ts` descreve o escopo em duas
descrições que deixam de ser verdadeiras: `"Lê o subtree do folder Products via
MCP. Fora do root, nada é visitado."` (linha 35) e `"Top-k no pgvector, escopado
ao root, cortado pela distância máxima."` (linha 108). Ambas passam a falar em
roots, no mesmo commit da mudança — é a regra do CLAUDE.md que impede a página
de ops de mentir sobre a arquitetura. Nenhum arquivo declarado no mapa é
renomeado ou removido, então `architectureMap.test.ts` continua passando.

---

## Fase 1b — Home vira o chat

### Rotas

| Rota | Destino |
|---|---|
| `/` | `ChatPage` (conversa nova) |
| `/c/:conversationId` | `ChatPage` (conversa existente) |
| `/ops` | `OpsPage`, sem link em lugar nenhum |
| `/oracle`, `/oracle/:id` | redirect para `/` e `/c/:id` |

Os redirects existem porque links de `/oracle/:id` já foram compartilhados. O
`ChatPage` navega para `/oracle/:id` ao adotar uma conversa recém-criada
(`ChatPage.tsx:107`) e ao começar uma nova (`ChatPage.tsx:140`); os dois pontos
mudam para o formato novo.

### Remoções

Deletados por completo, com CSS modules e testes:

- `frontend/src/features/landing/` — `LandingPage`, `Hero`, `HowItWorks`,
  `Differentiators`, `FinalCta`
- `frontend/src/features/about/` — `AboutPage`
- `frontend/src/features/knowledge/` — `KnowledgePage`

Nenhum endpoint de backend é removido. `ListKnowledgeSectionsAction` e
`CountKnowledgeBaseAction` continuam em uso pela `AnswerQuestionAction` e pelo
`GetOpsOverviewAction`; a `KnowledgePage` era conteúdo estático.

### Header e Footer

Sobrevivem, porque a `OpsPage` os usa. O `Header` perde os links "Sobre &
Fontes", "Base de conhecimento" e o CTA "Abrir o oráculo →", restando a marca e
o toggle de tema. `Header.test.tsx` cobre exatamente esses links e é atualizado
junto.

O link "Ops" também sai do header — a página passa a ser alcançável só por quem
digitar a URL, conforme combinado na reunião. A guarda `isAdmin` em `App.tsx`
permanece, pronta para a Fase 3.

### Empty state

O `ChatPage` já renderiza `EmptyState` quando não há histórico, com o composer
liberado logo abaixo — a estrutura que Yuri pediu já existe. Muda o conteúdo:

- Os exemplos passam a sair dos roots liberados (Products, Código de Cultura,
  Mapa Global de Papéis, Domínios & Subdomínios). Os atuais — "nomenclatura de
  campanhas no Meta Ads" (Growth & Marketing) e "upload semanal de vídeo no
  YouTube" (operação) — apontam para fora do escopo e hoje levam direto à recusa
  padrão.
- O card `[demo-error]`, que dispara o estado de erro de propósito, é removido.

### Identidade placeholder

`ChatPage.tsx:15` define `USER_EMAIL = "duanne@mail.com"`, exibido na topbar e na
sidebar. Sem autenticação, todo mundo do ecossistema veria esse endereço como se
fosse a própria identidade. O chip de e-mail sai no MVP e volta na Fase 3,
quando houver `/me`.

### Testes

- Roteamento: `/` renderiza o chat; `/c/:id` carrega a conversa; `/oracle/:id`
  redireciona para `/c/:id`; `/about` e `/knowledge` não resolvem.
- `Header` renderiza apenas marca e toggle.
- `EmptyState` não expõe o gatilho de erro de demonstração.
- Nenhum import remanescente das features deletadas (o build com
  `tsc --noEmit` cobre isso).

---

## Fase 1c — Deploy

O alvo **não é decidido nesta spec**. A reunião estabeleceu o subdomínio
`oracle.<domínio>.com` e que a Borderless usa Cloudflare, mas Cloudflare resolve
DNS e frontend estático — o backend é FastAPI com Postgres e pgvector, que
precisa de um host de container. O repositório tem `docker/Dockerfile` e
`docker-compose.yml` de desenvolvimento, e nenhuma configuração de deploy ou CI.

Passos, nesta ordem:

1. Ler como os projetos incubados (Roni, Sócrates Dev) subiram, para descobrir o
   padrão da casa.
2. Falar com o Natan a partir da semana de 10/08 — Yuri passa o contato — sobre
   o padrão de infraestrutura e o apontamento do subdomínio.
3. Só então escolher o alvo e escrever a spec de deploy.

Adotar um caminho próprio antes dessa conversa arriscaria construir algo que
depois é desfeito para seguir o padrão da Borderless.

## Critérios de aceite da Fase 1

- Uma pergunta sobre Código de Cultura ou Mapa Global de Papéis é respondida com
  citação da fonte correta — hoje ela recebe a recusa padrão.
- Um documento cujo `kb_root_page_id` não pertence à lista de roots não é
  recuperado nem citado, mesmo sem sync ter rodado.
- `knowledge:roots` reporta corretamente páginas liberadas fora da allowlist.
- A raiz do site abre o chat, com o composer utilizável de imediato.
- Nenhuma rota, link ou componente das páginas deletadas permanece.
- `pytest` e o build do frontend passam; `alembic check` continua limpo.

## Pendências

- **Confirmar a allowlist com Yuri** — em especial `Borderless Coding Labs` e
  `Borderless Copy Bible`, liberados mas não mencionados. Bloqueia apenas o
  valor final da variável de ambiente, não a implementação.
- **Contato do Natan** — Yuri passa a partir da semana de 10/08. Bloqueia 1c.
- **Páginas novas prometidas** — Yuri disse que criaria seções adicionais para
  consumo do oráculo. Quando existirem, o relatório de drift as detecta.
