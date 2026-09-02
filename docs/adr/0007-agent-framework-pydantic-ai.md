# ADR-0007 — Framework do agente = Pydantic AI (agnóstico de provedor)

## Status

Aceito — 2026-07-02. **Superseded por [ADR-0016](0016-agent-framework-langgraph.md) — 2026-09-01.**

## Resumo

- **Decisão:** o motor de orquestração do agente (oráculo) é o **Pydantic AI**, hospedado em `src/support/agent/` e consumido pelo domínio por uma fronteira fina.
- **Aplica-se quando:** for implementar ou evoluir a lógica do agente (tool calling, retrieval, seleção de modelo, streaming).
- **Regra prática:** toda a mágica do framework fica em `support/`. O domínio (`conversations/`, `documents/`) chama o agente via uma interface fina; Actions não importam Pydantic AI direto.

---

## Contexto

O oráculo é, no MVP, **um único agente que usa tools** (RAG sobre Notion + web search) com citação de fontes. Requisitos que pesam na escolha:

- **Multi-provedor:** precisa rodar com **Claude (Anthropic) ou GPT (OpenAI)**, selecionável via `LLM_PROVIDER` (ver stack no `CLAUDE.md`).
- **Arquitetura limpa:** o projeto tem regras inegociáveis de camadas (`app → domain → support`); abstrações de framework não podem vazar para o domínio.
- **MCP nativo:** a base de conhecimento vem do Notion via MCP; o framework precisa ser bom cliente MCP.
- **Stack existente:** Pydantic v2 e `pydantic-settings` já são núcleo.

## Decisão

Adotar **Pydantic AI** como núcleo do agente.

- Vive em `src/support/agent/` (config do Agent, seleção de modelo, registro de tools, system prompt).
- O domínio consome via uma **fronteira fina** (ex.: um serviço/porta em `support/` que expõe `answer(question, history) -> AnswerResult`).
- Seleção de provedor (Claude/GPT) reaproveita `LLM_PROVIDER` das settings.

## Consequências

**Positivas**
- Encaixa na stack (Pydantic v2, DI no estilo FastAPI), type-safe, pouca mágica.
- Agnóstico de provedor de forma limpa — atende Claude **ou** GPT sem reescrever domínio.
- Tool calling, structured output, streaming e **cliente MCP** nativos.
- Não briga com a arquitetura de camadas: o framework fica contido em `support/`.
- Caminho de evolução: **Pydantic Graph** quando o fluxo virar multi-agente/graph.

**Negativas / riscos**
- Ecossistema mais jovem que LangChain (menos integrações prontas) — mitigado por usarmos MCP + tools custom de qualquer forma.
- Dependência nova (`pydantic-ai`) — aprovada nesta decisão (contorna a regra 10).

## Alternativas consideradas

- **LangChain (core):** rejeitado — abstrações instáveis e que vazam, briga com a arquitetura limpa.
- **LangGraph:** adiado — excelente para fluxos genuinamente graph-shaped (multi-agente, human-in-the-loop, checkpoints), mas overkill para um tool-loop único; sua persistência duplicaria Postgres + `conversations`. Reconsiderar quando o fluxo exigir grafo.
- **SDK direto / Claude Agent SDK:** rejeitado como núcleo — o Claude Agent SDK é otimizado para Claude e empurra para lock-in, conflitando com o requisito multi-provedor. Um tool-loop cross-provider feito à mão é trabalho desnecessário agora.
