# Retrieval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cheap small-model retrieval gate that decides, before RAG, whether a turn needs the knowledge base and — when it does — supplies a standalone, context-resolved search query.

**Architecture:** The gate mirrors `OracleEngine`: `pydantic_ai` magic stays in `src/support/agent/`, exposed to the domain through a thin `RetrievalGatePort`. `AnswerQuestionAction` calls the gate before `SearchKnowledgeBaseAction`; on `retrieve=False` it injects no knowledge, on `retrieve=True` it retrieves with the gate's rewritten query. The gate fails open (any error → retrieve the raw question).

**Tech Stack:** Python 3.13, FastAPI, Pydantic AI (Anthropic/OpenAI), pytest + pytest-asyncio.

## Global Constraints

- Layering (rule #1): `src/domain/**` must not import `pydantic_ai`, `fastapi`, or `sqlalchemy`. Only `src/support/agent/retrieval_gate.py` (besides `oracle_engine.py`) may import `pydantic_ai`.
- Entities/DTOs that cross the domain boundary are plain dataclasses (rule #7). `RetrievalDecision` lives in `src/support/agent/ports.py` and stays framework-free.
- Provider selection reuses the existing `settings.LLM_PROVIDER` (`"anthropic" | "openai"`); API keys come from `settings`, never `os.environ` (match `oracle_engine._build_model`).
- Fail-open is mandatory: the gate may only ever *add* an unnecessary retrieval, never remove a necessary one.
- TDD, one behavior per test, frequent commits. Run tests with `uv run pytest` (repo uses UV).

---

### Task 1: Port types + settings

**Files:**
- Modify: `src/support/agent/ports.py`
- Modify: `src/support/core/settings.py` (near lines 47-51, the LLM block)
- Test: `tests/unit/support/agent/test_ports.py`

**Interfaces:**
- Produces: `RetrievalDecision(retrieve: bool, search_query: str)` dataclass; `RetrievalGatePort` Protocol with `async def decide(self, question: str, history: list[AgentMessage]) -> RetrievalDecision`. Settings: `ANTHROPIC_SMALL_MODEL: str`, `OPENAI_SMALL_MODEL: str`, `GATE_TIMEOUT_SECONDS: float`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/support/agent/test_ports.py` (create the file with the imports below if it does not exist):

```python
from src.support.agent.ports import RetrievalDecision
from src.support.core.settings import settings


def test_retrieval_decision_holds_flag_and_query():
    d = RetrievalDecision(retrieve=True, search_query="renovação de PSP")
    assert d.retrieve is True
    assert d.search_query == "renovação de PSP"


def test_small_model_and_timeout_settings_have_defaults():
    assert settings.ANTHROPIC_SMALL_MODEL
    assert settings.OPENAI_SMALL_MODEL
    assert settings.GATE_TIMEOUT_SECONDS > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/support/agent/test_ports.py -v`
Expected: FAIL — `ImportError: cannot import name 'RetrievalDecision'` (and/or `AttributeError` on settings).

- [ ] **Step 3: Add the types to `src/support/agent/ports.py`**

Add alongside the existing dataclasses/Protocol (the file already imports `dataclass`, `Protocol`, `AsyncIterator`, `Literal` and defines `AgentMessage`):

```python
@dataclass
class RetrievalDecision:
    """Decisão do retrieval gate: recuperar ou não, e a query já resolvida."""

    retrieve: bool
    search_query: str  # standalone, context-resolved; "" quando retrieve é False


class RetrievalGatePort(Protocol):
    async def decide(
        self, question: str, history: list[AgentMessage]
    ) -> RetrievalDecision: ...
```

- [ ] **Step 4: Add the settings fields to `src/support/core/settings.py`**

Directly below the existing `OPENAI_MODEL: str = "gpt-4o"` line (currently line 51):

```python
    ANTHROPIC_SMALL_MODEL: str = "claude-haiku-4-5-20251001"
    OPENAI_SMALL_MODEL: str = "gpt-4o-mini"
    GATE_TIMEOUT_SECONDS: float = 5.0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/support/agent/test_ports.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/support/agent/ports.py src/support/core/settings.py tests/unit/support/agent/test_ports.py
git commit -m "feat(agent): add RetrievalDecision/RetrievalGatePort + small-model settings"
```

---

### Task 2: RetrievalGate implementation (fail-open, timeout, blank-query coercion)

**Files:**
- Create: `src/support/agent/retrieval_gate.py`
- Test: `tests/unit/support/agent/test_retrieval_gate.py`

**Interfaces:**
- Consumes: `RetrievalDecision`, `AgentMessage` from `src/support/agent/ports.py`; `settings` from `src/support/core/settings.py`.
- Produces: `class RetrievalGate` with `__init__(self, agent=None)` and `async def decide(self, question, history) -> RetrievalDecision`; module function `get_retrieval_gate() -> RetrievalGate`. The injectable `agent` is any object exposing `async def run(prompt) -> result` where `result.output` is a `RetrievalDecision` (matches `pydantic_ai.Agent`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/support/agent/test_retrieval_gate.py`:

```python
import asyncio

import pytest

from src.support.agent.ports import AgentMessage, RetrievalDecision
from src.support.agent.retrieval_gate import RetrievalGate


class _Result:
    def __init__(self, output):
        self.output = output


class _StubAgent:
    """Fake pydantic-ai agent: returns a preset output or raises."""

    def __init__(self, output=None, raises=None):
        self._output = output
        self._raises = raises
        self.prompt = None

    async def run(self, prompt):
        self.prompt = prompt
        if self._raises is not None:
            raise self._raises
        return _Result(self._output)


@pytest.mark.asyncio
async def test_passes_through_a_valid_retrieve_decision():
    agent = _StubAgent(output=RetrievalDecision(retrieve=True, search_query="renovação de PSP"))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("e as renovações?", [AgentMessage("user", "fale do PSP")])

    assert decision.retrieve is True
    assert decision.search_query == "renovação de PSP"


@pytest.mark.asyncio
async def test_passes_through_a_skip_decision():
    agent = _StubAgent(output=RetrievalDecision(retrieve=False, search_query=""))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("valeu!", [])

    assert decision.retrieve is False
    assert decision.search_query == ""


@pytest.mark.asyncio
async def test_fails_open_on_error_retrieving_raw_question():
    agent = _StubAgent(raises=RuntimeError("boom"))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"


@pytest.mark.asyncio
async def test_fails_open_on_timeout():
    agent = _StubAgent(raises=asyncio.TimeoutError())
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"


@pytest.mark.asyncio
async def test_coerces_blank_query_to_raw_question():
    agent = _StubAgent(output=RetrievalDecision(retrieve=True, search_query="   "))
    gate = RetrievalGate(agent=agent)

    decision = await gate.decide("qual o onboarding?", [])

    assert decision.retrieve is True
    assert decision.search_query == "qual o onboarding?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/support/agent/test_retrieval_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.support.agent.retrieval_gate'`.

- [ ] **Step 3: Write the implementation**

Create `src/support/agent/retrieval_gate.py`:

```python
"""Retrieval gate sobre Pydantic AI (ADR-0007): decide, com um modelo PEQUENO,
se o turno precisa da base de conhecimento e, em caso positivo, devolve uma query
de busca autônoma (contexto da conversa resolvido). Fail-open: qualquer erro
recupera a pergunta crua. Segundo (e único outro) lugar que importa pydantic_ai."""

import asyncio
import logging

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from src.support.agent.ports import AgentMessage, RetrievalDecision
from src.support.core.settings import settings

logger = logging.getLogger(__name__)

GATE_SYSTEM_PROMPT = """\
Você é um roteador para a base de conhecimento do Oracle Borderless (documentos
curados do Notion: SOPs, processos de negócio, editoriais, dados operacionais).
Decida se responder à ÚLTIMA mensagem do usuário exige buscar nessa base.

- retrieve=false para: saudações, agradecimentos, conversa fiada, perguntas sobre
  você mesmo, e qualquer coisa totalmente respondível pelo histórico da conversa.
- retrieve=true para qualquer pergunta substantiva sobre o ecossistema, suas regras
  ou dados operacionais.

Quando retrieve=true, devolva também search_query: uma query AUTÔNOMA, no idioma da
pergunta, resolvendo pronomes/elipses a partir da conversa (ex.: "e as renovações?"
-> "renovação de PSP"). Quando retrieve=false, search_query é "".
"""


def _build_small_model():
    if settings.LLM_PROVIDER == "openai":
        return OpenAIChatModel(
            settings.OPENAI_SMALL_MODEL,
            provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY),
        )
    return AnthropicModel(
        settings.ANTHROPIC_SMALL_MODEL,
        provider=AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY),
    )


def _build_gate_agent() -> Agent:
    return Agent(
        _build_small_model(),
        system_prompt=GATE_SYSTEM_PROMPT,
        output_type=RetrievalDecision,
    )


def _build_prompt(question: str, history: list[AgentMessage]) -> str:
    parts = [f"{m.role}: {m.content}" for m in history]
    parts.append(f"Mensagem atual do usuário: {question}")
    return "\n\n".join(parts)


class RetrievalGate:
    def __init__(self, agent=None) -> None:
        self._agent = agent or _build_gate_agent()

    async def decide(
        self, question: str, history: list[AgentMessage]
    ) -> RetrievalDecision:
        prompt = _build_prompt(question, history)
        try:
            result = await asyncio.wait_for(
                self._agent.run(prompt), timeout=settings.GATE_TIMEOUT_SECONDS
            )
            decision = result.output
        except Exception:  # fail-open: uma recuperação a mais > uma perdida
            logger.warning("retrieval gate falhou; fail-open (query crua)", exc_info=True)
            return RetrievalDecision(retrieve=True, search_query=question)

        if decision.retrieve and not decision.search_query.strip():
            return RetrievalDecision(retrieve=True, search_query=question)
        return decision


def get_retrieval_gate() -> "RetrievalGate":
    return RetrievalGate()
```

Note: `result.output` is the current Pydantic AI accessor for structured output. Our unit tests inject a fake agent with `.output`, so the gate's contract is verified regardless of the installed SDK version; production correctness of the accessor is exercised by a real call during manual smoke-testing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/support/agent/test_retrieval_gate.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/support/agent/retrieval_gate.py tests/unit/support/agent/test_retrieval_gate.py
git commit -m "feat(agent): RetrievalGate (small model, fail-open, query rewrite)"
```

---

### Task 3: Wire the gate into AnswerQuestionAction

**Files:**
- Create: `tests/fakes/fake_retrieval_gate.py`
- Modify: `src/domain/conversations/actions/answer_question_action.py`
- Modify: `tests/unit/domain/conversations/actions/test_answer_question_action.py` (the `_make` helper + new cases)

**Interfaces:**
- Consumes: `RetrievalGatePort`, `RetrievalDecision` from `src/support/agent/ports.py`.
- Produces: `AnswerQuestionAction.__init__(self, engine, search, gate)` (new required `gate` param); `FakeRetrievalGate(retrieve: bool = True, search_query: str | None = None)` with `async def decide(...)` and a `received` attribute.

- [ ] **Step 1: Create the test fake**

Create `tests/fakes/fake_retrieval_gate.py`:

```python
"""Gate fake — implementa RetrievalGatePort sem chamar LLM."""

from src.support.agent.ports import AgentMessage, RetrievalDecision


class FakeRetrievalGate:
    def __init__(self, retrieve: bool = True, search_query: str | None = None) -> None:
        self._retrieve = retrieve
        self._search_query = search_query
        self.received: tuple[str, list[AgentMessage]] | None = None

    async def decide(self, question: str, history: list[AgentMessage]) -> RetrievalDecision:
        self.received = (question, history)
        if not self._retrieve:
            return RetrievalDecision(retrieve=False, search_query="")
        query = self._search_query if self._search_query is not None else question
        return RetrievalDecision(retrieve=True, search_query=query)
```

- [ ] **Step 2: Write the failing tests**

In `tests/unit/domain/conversations/actions/test_answer_question_action.py`, first update the shared `_make` helper so it injects a gate (keeps existing cases green by defaulting to always-retrieve):

```python
def _make(engine, search, conv_repo, msg_repo, gate=None):
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    action = AnswerQuestionAction(
        engine=engine, search=search, gate=gate or FakeRetrievalGate(retrieve=True)
    )
    action.conversations = conv_repo
    action.messages = msg_repo
    return action
```

Then replace the module-level `_FakeSearch` with a recording version and add the two new cases at the end of the file:

```python
class _RecordingSearch:
    def __init__(self):
        self.calls = []

    async def execute(self, query):
        self.calls.append(query)
        from src.support.agent.ports import KnowledgeSnippet
        from src.domain.shared.value_objects.citation import Citation

        return [KnowledgeSnippet("trecho", Citation("notion", "Doc", "https://n/a", "t", "a"))]


@pytest.mark.asyncio
async def test_gate_skip_injects_no_knowledge_and_skips_search():
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    search = _RecordingSearch()
    action = _make(engine, search, conv_repo, msg_repo, gate=FakeRetrievalGate(retrieve=False))

    _cid, stream = await action.execute("valeu!", None, "a@x.com")
    async for _ in stream:  # drena o stream
        pass

    assert search.calls == []  # não recuperou


@pytest.mark.asyncio
async def test_gate_retrieve_uses_rewritten_query():
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    engine, conv_repo, msg_repo = _FakeEngine(), _FakeConvRepo(), _FakeMsgRepo()
    search = _RecordingSearch()
    gate = FakeRetrievalGate(retrieve=True, search_query="renovação de PSP")
    action = _make(engine, search, conv_repo, msg_repo, gate=gate)

    _cid, stream = await action.execute("e as renovações?", None, "a@x.com")
    async for _ in stream:
        pass

    assert search.calls == ["renovação de PSP"]  # query reescrita, não a crua
```

Note: `_FakeEngine.stream_answer` in this file already accepts `(question, history, knowledge)`. Keep the existing `_FakeSearch` class only if other tests reference it; the new tests use `_RecordingSearch`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/domain/conversations/actions/test_answer_question_action.py -v`
Expected: FAIL — `TypeError: AnswerQuestionAction.__init__() got an unexpected keyword argument 'gate'`.

- [ ] **Step 4: Modify `AnswerQuestionAction`**

In `src/domain/conversations/actions/answer_question_action.py`:

Update imports (add the port type):

```python
from src.support.agent.ports import AgentStreamChunk, OracleEnginePort, RetrievalGatePort
```

Update `__init__`:

```python
    def __init__(
        self, engine: OracleEnginePort, search: SearchKnowledgeBaseAction, gate: RetrievalGatePort
    ) -> None:
        self.engine = engine
        self.search = search
        self.gate = gate
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
```

Replace the retrieval section (currently lines ~54-67, from `history = ...` to the `return`):

```python
        history = await self.messages.load_recent(conversation.uuid)

        decision = await self.gate.decide(question, history)

        await self.messages.append(
            Message(
                uuid=uuid7(),
                conversation_id=conversation.uuid,
                role="user",
                content=question,
                created_at=now,
            )
        )

        if decision.retrieve:
            knowledge = await self.search.execute(decision.search_query)  # query reescrita
        else:
            knowledge = []  # nada injetado — sem poluição de contexto

        return conversation.uuid, self.engine.stream_answer(question, history, knowledge)
```

(The engine still receives the raw `question`; only retrieval uses the rewritten query.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/domain/conversations/actions/test_answer_question_action.py -v`
Expected: PASS (existing cases + the two new ones).

- [ ] **Step 6: Commit**

```bash
git add tests/fakes/fake_retrieval_gate.py src/domain/conversations/actions/answer_question_action.py tests/unit/domain/conversations/actions/test_answer_question_action.py
git commit -m "feat(conversations): gate retrieval in AnswerQuestionAction (skip + rewrite)"
```

---

### Task 4: Wire the gate into the controller

**Files:**
- Modify: `src/app/api/controllers/conversation_controller.py`
- Modify: `tests/integration/api/test_ask_endpoint.py` (stub the gate in both tests)

**Interfaces:**
- Consumes: `get_retrieval_gate` from `src/support/agent/retrieval_gate.py`; `AnswerQuestionAction(engine, search, gate)` from Task 3.

- [ ] **Step 1: Update the integration tests to stub the gate (failing first)**

In `tests/integration/api/test_ask_endpoint.py`, add to BOTH `test_ask_streams_and_persists_both_turns` and `test_ask_failure_emits_error_and_does_not_persist_assistant`, next to the existing `monkeypatch.setattr(ctrl, "get_oracle_engine", ...)` lines:

```python
    from tests.fakes.fake_retrieval_gate import FakeRetrievalGate

    monkeypatch.setattr(ctrl, "get_retrieval_gate", lambda: FakeRetrievalGate(retrieve=True))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/api/test_ask_endpoint.py -v`
Expected: FAIL — `AttributeError: <module 'conversation_controller'> does not have the attribute 'get_retrieval_gate'` (monkeypatch can't patch a name the module hasn't imported yet).

- [ ] **Step 3: Wire the gate in the controller**

In `src/app/api/controllers/conversation_controller.py`, add the import next to `from src.support.agent.oracle_engine import get_oracle_engine`:

```python
from src.support.agent.retrieval_gate import get_retrieval_gate
```

Update the action construction inside `ask`:

```python
        search = SearchKnowledgeBaseAction(embeddings=get_embeddings_client())
        action = AnswerQuestionAction(
            engine=get_oracle_engine(),
            search=search,
            gate=get_retrieval_gate(),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/api/test_ask_endpoint.py -v`
Expected: PASS. (Requires the pgvector test DB up — see the port-conflict note; if the DB is down these integration tests are skipped/errored by environment, not by this change.)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all previously-green tests still pass, plus the new gate tests.

- [ ] **Step 6: Commit**

```bash
git add src/app/api/controllers/conversation_controller.py tests/integration/api/test_ask_endpoint.py
git commit -m "feat(api): wire retrieval gate into /conversations/ask"
```

---

## Self-Review

**Spec coverage:**
- Ports (`RetrievalDecision`, `RetrievalGatePort`) → Task 1. ✅
- `retrieval_gate.py` (small model, structured output, `get_retrieval_gate`) → Task 2. ✅
- Settings (`ANTHROPIC_SMALL_MODEL`, `OPENAI_SMALL_MODEL`, `GATE_TIMEOUT_SECONDS`) → Task 1. ✅
- `AnswerQuestionAction` gate wiring (skip → `[]`, retrieve → rewritten query, engine gets raw question) → Task 3. ✅
- Controller wiring → Task 4. ✅
- `FakeRetrievalGate` → Task 3. ✅
- Fail-open / timeout / blank-query coercion → Task 2 tests. ✅
- Deterministic regression cases (skip path, retrieve path, fail-open, blank coercion) → Tasks 2 & 3. ✅
- Out-of-scope items (dead `llm_client.py`, parallelization, relevance-threshold) → intentionally untouched. ✅

**Placeholder scan:** none — every code/step is concrete.

**Type consistency:** `RetrievalDecision(retrieve, search_query)`, `decide(question, history)`, `AnswerQuestionAction(engine, search, gate)`, `get_retrieval_gate()`, `FakeRetrievalGate(retrieve, search_query)` are used identically across all tasks. ✅
