# Architecture Decision Records (ADRs)

ADRs registram **o raciocínio por trás** de decisões arquiteturais importantes. São
**imutáveis**: para mudar uma decisão, crie um ADR novo que substitua o anterior.

## Como ler (leitura progressiva — economiza contexto)

Cada ADR tem uma seção `## Resumo` logo após o `## Status`, separada do corpo completo
por `---`. Fluxo recomendado:

1. Comece por este índice.
2. Leia só o `## Resumo` do ADR candidato — se bastar ou não se aplicar, pare aqui.
3. Leia o corpo completo (abaixo do `---`) só se precisar do racional detalhado.

## Índice de ADRs

| # | Título | Status |
|---|---|---|
| [0001](0001-estrutura-spatie-like.md) | Adotar estrutura Spatie-like (`src/{app, domain, support}`) | *referenciado — a formalizar* |
| [0002](0002-domain-por-bounded-context.md) | Organizar `domain/` por bounded context | *referenciado — a formalizar* |
| [0003](0003-entities-vs-models.md) | Separar Entities (dataclass) de Models (SQLAlchemy) | *referenciado — a formalizar* |
| [0004](0004-actions-sem-service-facade.md) | Actions com sufixo `Action`/`execute()`, sem Service facade | *referenciado — a formalizar* |
| [0005](0005-sqlalchemy-vs-sqlmodel.md) | Usar SQLAlchemy 2.0 em vez de SQLModel | *referenciado — a formalizar* |
| [0006](0006-sessao-db-via-contextvar.md) | Sessão DB via ContextVar + middleware | *referenciado — a formalizar* |
| [0007](0007-agent-framework-pydantic-ai.md) | Framework do agente = Pydantic AI (agnóstico de provedor) | *substituído pelo 0016* |
| [0008](0008-rag-hibrido-pgvector-mcp.md) | RAG híbrido (pgvector + MCP) e embeddings OpenAI | Aceito |
| [0009](0009-streaming-sse.md) | Streaming das respostas do chat via SSE | *contrato substituído pelo 0019 (transporte SSE mantido)* |
| [0010](0010-transporte-mcp-notion.md) | Transporte do Notion: MCP server via cliente `mcp` (não SDK REST) | Aceito |
| [0011](0011-kb-restrita-root-notion.md) | Base de conhecimento restrita ao subtree de um root configurável do Notion | *substituído pelo 0015* |
| [0012](0012-escopo-kb-aplicado-na-recuperacao.md) | Escopo da KB aplicado também na recuperação, não só na descoberta | *parcialmente substituído pelo 0015* |
| [0013](0013-trace-por-turno-no-postgres.md) | Trace por turno persistido no Postgres, coletado num ponto único | Aceito |
| [0014](0014-kb-multi-root.md) | KB é a união dos subtrees de múltiplos roots do Notion | *substituído pelo 0015* |
| [0015](0015-kb-escopo-descoberto-pela-permissao.md) | Escopo da KB descoberto pela permissão do Notion | Aceito |
| [0016](0016-agent-framework-langgraph.md) | Framework do agente = LangGraph, observabilidade fina no LangSmith | *consumo em duas fases revisado pelo 0020* |
| [0017](0017-auth-plataforma-como-idp.md) | Plataforma Borderless como IdP; JWT local; sem Supabase | *validação/sessão substituídas pelo 0018* |
| [0018](0018-auth-bff-token-opaco.md) | Auth vira BFF: token opaco da plataforma vive só no servidor | Aceito |
| [0019](0019-contrato-ag-ui-do-turno.md) | O turno do oráculo é entregue como eventos AG-UI | *contrato substituído pelo 0021 (regra 4 e passos mantidos)* |
| [0020](0020-fase-1-do-turno-no-corpo-sse.md) | A fase 1 do turno roda no corpo SSE, em escopo de sessão próprio | Aceito |
| [0021](0021-turno-como-stream-event.md) | O turno é entregue como `StreamEvent` do `astream_events` (substitui o contrato do 0019) | Aceito |
| [0022](0022-tool-de-navegacao.md) | Tool de navegação: nó `navigate` dedicado, sessões por bearer e catálogo por turno | Aceito |

> ADR-0001–0006 são citados pelo `CLAUDE.md` mas ainda não foram escritos como arquivo.
> As regras já estão em vigor (ver `CLAUDE.md` → "Regras inegociáveis"). Backfill quando
> houver necessidade.

## Template de ADR novo

Todo ADR novo deve começar com `## Status` e `## Resumo` (três blocos), depois `---` e o corpo:

```markdown
# ADR-XXXX — Título curto e imperativo

## Status

Aceito — YYYY-MM-DD.

## Resumo

- **Decisão:** uma frase com o que foi decidido.
- **Aplica-se quando:** o gatilho para consultar este ADR.
- **Regra prática:** o que fazer na prática, direto.

---

## Contexto
...
## Decisão
...
## Consequências
...
## Alternativas consideradas
...
```

## Regras de uso

- ADRs são **imutáveis**. Mudança de rumo = ADR novo que substitui.
- **Antes de criar um ADR novo, leia este README.**
- **Todo ADR novo deve ter `## Resumo` no topo.**
- Decisões novas com impacto arquitetural exigem ADR **antes** da implementação.
