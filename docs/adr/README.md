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
| [0007](0007-agent-framework-pydantic-ai.md) | Framework do agente = Pydantic AI (agnóstico de provedor) | Aceito |
| [0008](0008-rag-hibrido-pgvector-mcp.md) | RAG híbrido (pgvector + MCP) e embeddings OpenAI | Aceito |
| [0009](0009-streaming-sse.md) | Streaming das respostas do chat via SSE | Aceito |
| [0010](0010-transporte-mcp-notion.md) | Transporte do Notion: MCP server via cliente `mcp` (não SDK REST) | Aceito |
| [0011](0011-kb-restrita-root-notion.md) | Base de conhecimento restrita ao subtree de um root configurável do Notion | Aceito |

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
