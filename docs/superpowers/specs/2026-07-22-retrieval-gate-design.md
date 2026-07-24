# Design — Retrieval Gate (quality-led, skip + query rewrite)

**Date:** 2026-07-22
**Status:** Approved (brainstorming) — pending implementation plan
**Related:** ADR-0007 (Pydantic AI agent), ADR-0008 (RAG híbrido pgvector + MCP)

## Problem

Today [`AnswerQuestionAction.execute`](../../../src/domain/conversations/actions/answer_question_action.py)
runs `search.execute(question)` — an embedding call **plus** a pgvector top-k query —
**unconditionally on every turn**, including greetings, thanks, and meta questions
("who are you?"). Two costs follow:

1. **Answer-quality (primary):** on turns that don't need the knowledge base, top-k still
   returns up to `RAG_TOP_K` (6) marginally-similar chunks that get injected into the
   prompt and can bias or derail the answer ("over-interpretation"). This is the main
   problem we are solving.
2. **Cost + latency (secondary):** a wasted embedding + vector query on trivial turns.

Additionally, retrieval today embeds the **raw** `question`. In a multi-turn conversation,
follow-ups such as *"e as renovações?"* or *"e no caso de menores?"* embed poorly on their
own — they need conversation context folded in to retrieve well.

## Decision

Introduce a **retrieval gate**: a cheap **small-model** decision, made **before** retrieval,
that returns both *whether* to retrieve and, when yes, a **standalone, context-resolved
search query**. This is the Waku "retrieval gate" pattern (hero moment #1), adapted to the
oracle's network-RAG stack.

- **Primary goal:** protect answer quality by not injecting knowledge-base chunks on turns
  that don't need them.
- **Secondary benefit:** skip the embedding + vector query on skipped turns.
- **Bonus fix:** rewrite the retrieval query with conversation context, improving follow-up
  retrieval quality.

The gate can only ever **add** an unnecessary retrieval (the current behavior), never
**remove** a necessary one — see Fail-open.

## Architecture & components

The gate is the twin of `OracleEngine`: framework magic (`pydantic_ai`) stays in
`src/support/agent/`; the domain consumes a thin port (ADR-0007, layering rule #1).

### New — `src/support/agent/ports.py` (add to existing file)

```python
@dataclass
class RetrievalDecision:
    retrieve: bool
    search_query: str          # standalone, context-resolved query; "" when retrieve is False

class RetrievalGatePort(Protocol):
    async def decide(self, question: str, history: list[AgentMessage]) -> RetrievalDecision: ...
```

### New — `src/support/agent/retrieval_gate.py`

- `RetrievalGate` class: a `pydantic_ai.Agent` built with a **small model** and
  `output_type=RetrievalDecision` (structured output).
- `_build_small_model()`: mirrors `oracle_engine._build_model()` but reads the small-model
  id and injects the API key from `settings` (not the environment), same as the engine.
- `get_retrieval_gate()` factory, sibling to `get_oracle_engine()`.
- The gate's system prompt lives in this file, next to the code it drives (same convention
  as the engine's prompt).
- **Only** other file besides `oracle_engine.py` that imports `pydantic_ai`.

### Changed — `src/support/core/settings.py`

Add, reusing the existing `LLM_PROVIDER` switch:

- `ANTHROPIC_SMALL_MODEL: str = "claude-haiku-4-5-20251001"`
- `OPENAI_SMALL_MODEL: str = "gpt-4o-mini"`
- `GATE_TIMEOUT_SECONDS: float = 5.0` (bounded timeout; see Fail-open)

(Existing `ANTHROPIC_MODEL="claude-opus-4-8"`, `OPENAI_MODEL="gpt-4o"`, `LLM_PROVIDER`, and
the API keys are unchanged and reused.)

### Changed — `src/domain/conversations/actions/answer_question_action.py`

Inject `gate: RetrievalGatePort` in `__init__`; call it before search (see Data flow).

### Changed — `src/app/api/controllers/conversation_controller.py`

Wire `get_retrieval_gate()` into the action, exactly like `get_oracle_engine()`:

```python
action = AnswerQuestionAction(
    engine=get_oracle_engine(),
    search=search,
    gate=get_retrieval_gate(),
)
```

### New — `tests/fakes/fake_retrieval_gate.py`

A configurable fake returning a preset `RetrievalDecision`, sibling to
`tests/fakes/fake_oracle_engine.py`.

## Data flow (the turn, with the gate)

`AnswerQuestionAction.execute` becomes:

```
resolve/create conversation
  → history = load_recent(conversation)              # prior turns (unchanged)
  → decision = gate.decide(question, history)         # NEW — small model
  → persist user message                              # unchanged
  → if decision.retrieve:
        knowledge = search.execute(decision.search_query)   # rewritten query, NOT raw
    else:
        knowledge = []                                # nothing injected — no pollution
  → engine.stream_answer(question, history, knowledge)      # engine answers the RAW question
```

Two deliberate points:

1. The gate runs **serial before** retrieval because it produces the query — inherent to the
   skip+rewrite choice. The small model keeps the added latency small; we accept it because
   the goal is quality-led.
2. The rewrite feeds **retrieval only**. `stream_answer` still receives the raw `question`,
   so we never distort what the user actually asked.

## The gate's contract (prompt + I/O)

System prompt (in `retrieval_gate.py`):

> You are a routing gate for the Oracle Borderless knowledge base (curated Notion docs:
> SOPs, business processes, editorials, operational data). Decide whether answering the
> user's **latest** message requires searching that base.
> - `retrieve=false` for: greetings, thanks, small talk, meta questions about you, and
>   anything fully answerable from the conversation so far.
> - `retrieve=true` for any substantive question about the ecosystem, its rules, or
>   operational data.
> When `retrieve=true`, also return `search_query`: a **standalone** query in the language
> of the question, resolving pronouns/ellipsis from the conversation (e.g. "e as
> renovações?" → "renovação de PSP"). When `retrieve=false`, `search_query` is "".

- **Input:** the recent `history` (already loaded and token-budgeted) + the new `question`,
  assembled the same way `oracle_engine._build_prompt` composes history.
- **Output:** a validated `RetrievalDecision`.

## Error handling (fail-open — Waku's rule)

The gate must never lose a needed retrieval nor hang the turn:

- **Any exception / invalid output / parse failure** → return
  `RetrievalDecision(retrieve=True, search_query=question)` (raw question). *An extra
  retrieval beats a lost one.* Log a warning via stdlib `logging`, matching the engine.
- **Bounded timeout** (`GATE_TIMEOUT_SECONDS`) on the gate call → treated as an exception →
  fail open.
- **`retrieve=True` but blank/whitespace `search_query`** → coerce to the raw `question`, so
  retrieval never runs on an empty query.

Net invariant: the gate can only ever add an unnecessary retrieval (the pre-gate behavior),
never remove a necessary one.

## Testing (deterministic; sets up the judge-eval milestone)

Wiring is fully deterministic-testable with the fake gate injected into
`AnswerQuestionAction`. The model's *judgment quality* is deferred to the judge-eval design
(next). Regression cases (Waku §4.1 discipline — each becomes permanent):

- **Skip path** — fake gate `retrieve=False` → `search.execute` is **not called** and the
  engine receives `knowledge=[]`.
- **Retrieve path** — fake gate `retrieve=True, search_query="X"` → `search.execute` is
  called with **`"X"`, not the raw question** → engine gets those snippets.
- **Fail-open** — a real `RetrievalGate` wrapping a model that raises → `decide()` returns
  `retrieve=True, search_query=<raw question>`.
- **Blank-query coercion** — `retrieve=True, search_query="  "` → retrieval runs with the
  raw question.

Accuracy of the *decision itself* (correctly skipping a greeting, correctly rewriting a
follow-up) becomes a scored case in the judge-eval suite, not a 0/1 unit test.

## Out of scope (noted, not done)

- Cleanup of the dead `src/support/clients/llm/llm_client.py` (non-streaming, no-tools,
  unused by the answer path). Separate change.
- Parallelizing gate + a speculative retrieval — YAGNI; the rewrite makes them serial by
  design anyway.
- Relevance-threshold filtering of returned chunks — an alternative pollution defense not
  chosen here (gate was chosen instead).

## Trade-offs

**Gained:** cleaner answers on non-KB turns (primary), cost/latency saved on skipped turns,
and better follow-up retrieval via query rewrite.
**Lost:** one small-model round-trip added serially to substantive turns; a new
`support/agent` component and small-model settings. Consistent with the existing
engine/port seam, so the cost to legibility is low.
