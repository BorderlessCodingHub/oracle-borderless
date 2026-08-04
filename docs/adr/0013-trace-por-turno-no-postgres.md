# ADR-0013 — Trace por turno persistido no Postgres, coletado num ponto único

## Status

Aceito — 2026-08-04.

## Resumo

- **Decisão:** cada turno do oráculo grava uma linha em `agent_traces` (Postgres)
  com gate, retrieval, limiar, desfecho e latências. O sinal é acumulado num
  coletor único em memória (`TurnTraceDraft`) e escrito **pós-stream**, na mesma
  background task que já persiste a resposta do assistente.
- **Aplica-se quando:** for preciso saber o que aconteceu num turno, adicionar
  sinal novo de observabilidade, ou mexer no caminho `POST /conversations/ask`.
- **Regra prática:** sinal novo entra no draft **e** na tabela — não em log solto.
  Observabilidade nunca derruba um turno (call site sob `try/except` que loga e
  engole). Turno que terminou em erro também é gravado: é o que mais interessa.

---

## Contexto

Um turno passa por três decisões em série — o gate decide `skip`/`retrieve` e
reescreve a query, o limiar de distância decide o que vira contexto, e o prompt
decide entre responder e emitir a recusa padrão. Nenhuma delas deixava rastro.
Quando uma resposta saía errada não havia como saber qual das três falhou: o que
existia era `logging` de erro, nada sobre decisão, latência ou quantos chunks
passaram.

Isso também deixava o modelo de LLM-Ops pela metade: o judge eval já existe em
[`evals/`](../../evals/), mas o **trace**, que é o pré-requisito dele, não. Sem
trace, ajustar `RAG_TOP_K`, limiar ou prompt é palpite — e a página de ops não
teria número real para mostrar ao lado do desenho da arquitetura.

Três restrições moldaram a decisão:

1. **O filesystem do container é efêmero e não é compartilhado entre réplicas.**
   Trace em JSONL (como faz um agente que roda local, num processo) desapareceria
   a cada deploy e ficaria particionado por worker.
2. **A resposta é streamada por SSE** ([ADR-0009](0009-streaming-sse.md)). O
   `DBSessionMiddleware` já fechou a sessão do request quando o corpo SSE ainda
   está transmitindo — qualquer escrita depois disso precisa de sessão própria,
   como a persistência da mensagem do assistente do M2 já resolveu.
3. **Coleta não pode custar latência de resposta.** O usuário está lendo tokens
   enquanto isso.

## Decisão

**Uma linha por turno em `agent_traces`**, com as dimensões que se consulta em
colunas planas (gate, retrieval, desfecho, latências, tokens) e a sequência de
passos em `events` JSONB. Colunas planas porque é o que os agregados da página
somam em SQL; JSONB porque a sequência é lida inteira, num turno só.

**Coletor único, puro.** `TurnTraceDraft` (`src/domain/observability/dtos/`) é um
DTO com relógio injetável que acumula eventos ao longo do turno. A
`AnswerQuestionAction` preenche as fases que rodam dentro do request (recência,
gate, retrieval, recusa) e devolve o draft junto da resposta; o gerador SSE do
controller completa a fase do engine (primeiro token, duração, tokens, tool
calls). Não há um segundo lugar montando trace.

**Escrita pós-stream, uma sessão, duas escritas.** A mesma background task que
persiste a resposta grava o trace, via `run_in_async_session`. O trace vai
primeiro — turno que quebrou é o que mais interessa — e cada escrita é isolada,
para que a falha de uma não leve a outra embora.

**Observabilidade nunca derruba um turno.** O call site fica sob `try/except` que
loga e engole, como `_persist_assistant` já fazia. Uma linha de trace perdida é
aceitável; um turno perdido não.

**Leitura post-hoc, só-leitura.** Quatro endpoints (`/ops/overview`,
`/ops/turns`, `/ops/turns/{id}`, `/ops/eval`) agregam em SQL e servem a página
`/ops`. Acender ao vivo exigiria broker em processo e, com mais de uma réplica,
cada aba veria só os turnos do seu worker.

## Consequências

- Existe uma fonte única para responder "por que essa resposta saiu assim" —
  e um dado real para calibrar limiar, `top-k` e prompt na próxima conversa.
- **A tabela cresce sem poda.** Uma linha por turno, sem retenção na v1. No
  volume de um oráculo interno demora a importar; fica registrado como
  follow-up, não silenciado.
- **Tokens podem faltar.** `usage()` do pydantic-ai nem sempre entrega contagem
  no streaming (em 2.4.0 é *property*, não método). As colunas são nullable e a
  tela mostra "—" — degradação prevista, não bug.
- `src/support/observability/` passa a ser o lugar de I/O de observabilidade
  (hoje `EvalReportStore`; é onde um exportador OTel entraria depois).
- A página fica **aberta** enquanto a auth de admin não existe, com o encaixe
  pronto dos dois lados (`require_admin` no router, `useCurrentUser` no front).
  Por isso os responses de turno omitem `user_email`.
- O mapa da arquitetura na página é um registro único verificado por teste
  (`frontend/src/features/ops/architectureMap.ts`): arquivo declarado que some
  quebra o build. Ver a regra em `CLAUDE.md` → "Antes de fazer mudanças
  estruturais".

## Alternativas consideradas

- **JSONL em disco** (como um agente local faria): descartado pelo filesystem
  efêmero e pela partição entre réplicas.
- **Ao vivo, por broker ou segundo canal SSE:** descartado — complexidade de
  broker em processo e visão parcial por worker, sem ganho para diagnóstico
  post-hoc.
- **Instrumentar cada etapa gravando sua própria linha:** descartado — múltiplas
  escritas no caminho quente e nenhum ponto onde o turno é visto inteiro.
- **Só logging estruturado + agregador externo:** descartado por ora; exigiria
  infraestrutura nova para responder perguntas que uma tabela já responde.
