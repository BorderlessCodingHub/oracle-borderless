# AG-UI no turno do oráculo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /conversations/ask` passa a receber `RunAgentInput` e a responder eventos AG-UI (passos do grafo, tool calls, texto, fontes), e o chat mostra uma linha do tempo ao vivo do turno no lugar do indicador genérico de "pensando".

**Architecture:** O `AgentStreamChunk` do `TurnGraphPort` vira uma união de dataclasses puras (texto, fontes, passos, tool calls). O `runner.py` deixa de filtrar os `updates` dos nós e os `tool_call_chunks` do nó `answer` e sintetiza esses chunks, sem tocar em `builder`/`nodes`/`edges` nem no consumo em duas fases. A tradução chunk → evento AG-UI (`ag-ui-protocol`, só tipos Pydantic + `EventEncoder`) mora na camada `app`, em `src/app/api/streaming/`. O frontend traduz os eventos AG-UI para o `AskEvent` interno com parser próprio; o hook ganha `activity` e um componente `TurnTimeline` substitui o `ThinkingIndicator`.

**Tech Stack:** FastAPI, LangGraph 1.x, `ag-ui-protocol` 0.1.x (Python), React 19 + Vite + Vitest (frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-ag-ui-turno-design.md`

## Global Constraints

- Regra 1/ADR-0016: `src/domain/` não importa `langgraph`/`langchain*`; **`src/domain/` e `src/support/agent/` não importam `ag_ui`** (protocolo só em `src/app/`). Protegido por `tests/unit/support/agent/test_domain_boundary.py`.
- Regra 4: **nenhum evento carrega conteúdo de tool**. `TOOL_CALL_RESULT.content` é exatamente `{"status":"ok"}` ou `{"status":"error"}`.
- Regra 7: schemas Pydantic ficam em `src/app/api/`. O `RunAgentRequest` mora em `src/app/api/requests/run_agent_request.py`.
- Regra 10: única dependência nova no backend é `ag-ui-protocol>=0.1,<1`. Nenhuma dependência nova no frontend.
- ADR-0016 intacto: consumo em duas fases (`start()` dirige até a ENTRADA do nó `answer` ou até o update do `refuse`; falha de gate/retrieve sobe eager; falha do estágio de resposta é adiada para o gerador).
- Sem migration. Sem mudança em `messages`/`conversations`.
- CLAUDE.md "mapa honesto": `frontend/src/features/ops/architectureMap.ts` muda **no mesmo commit** que muda arquivos do pipeline (Task 8).
- `threadId` alheio → **404** (`ConversationAccessPolicy` lança `NotFoundError`; ADR-0017: nunca revelar que existe).
- Backend e frontend mudam o contrato juntos; não há compatibilidade com o formato SSE antigo (`event: token` etc.).
- Comandos: backend `uv run pytest ...`; frontend `cd frontend && npx vitest run <arquivo>`. Testes de integração (`tests/integration/`) usam o Postgres local, como os já existentes.
- Commits em português, no estilo do repo (`feat(...)`, `docs(...)`, `test(...)`), terminando com `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File Structure

**Backend — criar**
- `docs/adr/0019-contrato-ag-ui-do-turno.md` — ADR que substitui o 0009.
- `src/app/api/requests/run_agent_request.py` — `RunAgentRequest(RunAgentInput)` com os validadores (UUIDs, última mensagem `user` não vazia) e as propriedades `question`/`conversation_id`.
- `src/app/api/streaming/__init__.py`, `src/app/api/streaming/ag_ui_encoder.py` — `RunContext` + `to_events(chunk, ctx)` + `run_started/run_finished/run_error` + `encode(event)`.
- `tests/unit/app/api/requests/__init__.py`, `tests/unit/app/api/requests/test_run_agent_request.py`
- `tests/unit/app/api/streaming/__init__.py`, `tests/unit/app/api/streaming/test_ag_ui_encoder.py`

**Backend — modificar**
- `pyproject.toml` (+ `uv.lock`) — dependência.
- `src/support/agent/ports.py` — união de chunks.
- `src/support/agent/graph/runner.py` — `TurnEmitter`, fase 1 acumulando lista.
- `src/domain/conversations/actions/answer_question_action.py` — find-or-create por id.
- `src/app/api/controllers/conversation_controller.py` — `RunAgentRequest` + eventos AG-UI.
- `evals/runner.py` — `isinstance(chunk, TextChunk)`.
- `tests/fakes/fake_turn_graph.py`, `tests/unit/support/agent/test_ports.py`, `tests/unit/support/agent/test_domain_boundary.py`, `tests/unit/support/agent/graph/test_runner.py`, `tests/unit/evals/test_runner.py`, `tests/unit/domain/conversations/actions/test_answer_question_action.py`, `tests/integration/api/test_ask_endpoint.py`, `tests/integration/api/test_ask_trace_persistence.py`.
- `docs/adr/README.md`, `CLAUDE.md`, `README.md`, `docs/architecture.md`, `docs/superpowers/specs/2026-09-01-langgraph-langsmith-design.md`.

**Backend — remover**
- `src/app/api/requests/ask_question_request.py` (substituído pelo `RunAgentRequest`).

**Frontend — criar**
- `frontend/src/lib/api/agui.ts` — tipos dos eventos AG-UI, `parseAgUiEvent`, `parseAgUiStream`, `buildRunAgentInput`, `toAskEvents`.
- `frontend/src/lib/api/agui.test.ts`
- `frontend/src/features/chat/timelineLabels.ts` — `stepLabel`, `toolLabel`.
- `frontend/src/features/chat/components/TurnTimeline.tsx`, `TurnTimeline.test.tsx`

**Frontend — modificar**
- `frontend/src/lib/api/sse.ts` — `parseSSEData` (só `data:`).
- `frontend/src/lib/api/conversations.ts` — `askStream` monta `RunAgentInput` e traduz.
- `frontend/src/lib/types.ts` — `AskEvent` novo.
- `frontend/src/lib/demo/demoStream.ts` — eventos novos.
- `frontend/src/hooks/useAskStream.ts` (+ `.test.ts`) — `activity`, `applyActivity`, stream cortado.
- `frontend/src/features/chat/components/MessageBubble.tsx` (+ `.test.tsx`), `MessageList.tsx`, `ChatPage.tsx`, `ChatPage.module.css`.
- `frontend/src/features/ops/architectureMap.ts`.

**Frontend — remover**
- `frontend/src/features/chat/components/ThinkingIndicator.tsx`.

---

### Task 1: ADR-0019 + dependência `ag-ui-protocol`

**Files:**
- Create: `docs/adr/0019-contrato-ag-ui-do-turno.md`
- Modify: `docs/adr/README.md` (tabela "Índice de ADRs", linhas 31–36), `CLAUDE.md` (stack, linha ~33; lista de ADRs, linhas 457–458), `pyproject.toml` (bloco `dependencies`)

**Interfaces:**
- Produces: pacote `ag_ui` importável (`from ag_ui.core import RunAgentInput, EventType, ...`; `from ag_ui.encoder import EventEncoder`).

- [ ] **Step 1: Escrever o ADR-0019**

Criar `docs/adr/0019-contrato-ag-ui-do-turno.md`:

```markdown
# ADR-0019 — O turno do oráculo é entregue como eventos AG-UI

## Status

Aceito — 2026-09-04. Substitui o [ADR-0009](0009-streaming-sse.md) (contrato de
eventos do chat). O transporte SSE do 0009 permanece; muda o que trafega nele.

## Resumo

- **Decisão:** `POST /conversations/ask` recebe um `RunAgentInput` do protocolo
  **AG-UI** (Agent–User Interaction Protocol) e responde, sobre SSE, a sequência
  de eventos do protocolo: `RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`,
  `TEXT_MESSAGE_*`, `CUSTOM` (`oracle.step`, `oracle.sources`), `RUN_FINISHED`
  ou `RUN_ERROR`. A tradução dos chunks do grafo para esses eventos mora em
  `src/app/api/streaming/` (camada `app`), usando do pacote `ag-ui-protocol`
  apenas os tipos e o `EventEncoder`. `threadId` (= id da conversa) e `runId`
  (= run do LangSmith) são gerados pelo cliente.
- **Aplica-se quando:** for mexer no endpoint do chat, no que o frontend recebe
  durante um turno, no `AgentStreamChunk` do `TurnGraphPort`, ou for ligar
  outro cliente ao oráculo.
- **Regra prática:** o protocolo não entra em `src/domain/` nem em
  `src/support/agent/` (teste de fronteira). `TOOL_CALL_RESULT` carrega só
  `{"status": ...}` — nunca o conteúdo da tool (regra 4). Nada da linha do
  tempo é persistido: `messages` continua guardando só texto + fontes.

---

## Contexto

O ADR-0009 definiu um contrato SSE caseiro com cinco eventos (`conversation`,
`token`, `sources`, `error`, `done`). Ele bastava para "texto + fontes", mas
esconde tudo o que o grafo (ADR-0016) faz entre a pergunta e o primeiro token:
gate, retrieval, recusa e tool calls. Queremos mostrar isso na UI como linha do
tempo do turno, sem inventar mais um vocabulário próprio.

O AG-UI é um protocolo aberto exatamente para isso — eventos tipados de agente
para interface, sobre HTTP + SSE — com SDKs em Python e JS e adaptadores para
LangGraph, CrewAI, Pydantic AI etc.

## Decisão

1. **Entrada** é o `RunAgentInput` do protocolo. `threadId` é o id da conversa
   (UUID gerado pelo cliente; find-or-create escopado ao usuário; thread de outro
   usuário é 404 pela `ConversationAccessPolicy`). `runId` vira o `run_id` do
   LangSmith e o `langsmith_run_id` do trace. A pergunta é a última mensagem
   `user`; o restante do histórico do cliente é ignorado — a recência continua
   vindo do Postgres por orçamento de tokens. `tools`, `context`, `state`,
   `forwardedProps`, `resume` são aceitos e ignorados.
2. **Saída** segue o protocolo. Um `messageId` de assistente por run. Passos do
   grafo (`gate`, `retrieve`, `refuse`, `answer`) viram `STEP_STARTED/FINISHED`;
   detalhe útil (`retrieve`/`degraded` do gate, `kept` do retrieval) vai num
   `CUSTOM oracle.step`. Tool calls viram `TOOL_CALL_START/ARGS/END/RESULT`, com
   o result carregando só um status. Fontes vão num `CUSTOM oracle.sources` no
   fim. Falha no meio do stream é `RUN_ERROR` e encerra o stream sem
   `RUN_FINISHED`.
3. **Onde mora.** O `AgentStreamChunk` do port vira uma união de dataclasses
   puras (texto, fontes, passo, tool call start/args/end/result). O runner
   sintetiza esses chunks a partir dos `updates` e `messages` do LangGraph. A
   tradução para eventos AG-UI é da camada `app` (`src/app/api/streaming/`).
   Domínio, grafo e eval não conhecem `ag_ui`.
4. **Sem o adaptador pronto.** `ag-ui-langgraph` dirige o grafo por conta
   própria e assume checkpointer + `MessagesState`; isso colide com "sem
   checkpointer" (ADR-0016), com as dependências injetadas por request e com o
   consumo em duas fases. O protocolo é implementado por cima do nosso runner.
5. **Frontend com parser próprio.** Sem `@ag-ui/client`/CopilotKit enquanto não
   houver cliente externo; o estado do turno continua no `ChatPage`.

## Consequências

**Positivas**
- A UI mostra a linha do tempo do turno e as tool calls com vocabulário padrão.
- O endpoint é AG-UI de ponta a ponta: qualquer cliente do protocolo pluga sem
  código sob medida no servidor.
- `runId` do cliente = run do LangSmith: um turno da tela liga ao trace sem
  intermediário.

**Negativas / riscos**
- Por causa do consumo em duas fases, `RUN_STARTED` e os passos `gate` e
  `retrieve` chegam numa rajada com o primeiro token. A sequência está certa;
  os dois primeiros passos não "acendem" um a um. Tornar isso ao vivo exige
  mover a fase 1 para dentro do corpo SSE — fora deste ADR.
- O `RunAgentInput` exige `tools`, `context` e `forwardedProps` presentes; o
  cliente manda vazios.
- Deploy conjunto de backend e frontend: não há período de coexistência com o
  contrato do 0009.

## Alternativas consideradas

- **Manter o contrato caseiro e só acrescentar eventos** — rejeitado: mais um
  vocabulário próprio para manter, sem interoperabilidade.
- **`ag-ui-langgraph`** — rejeitado (item 4 acima).
- **`@ag-ui/client` / CopilotKit no frontend** — adiado: duplicaria o estado
  que o `ChatPage` já gerencia e traz RxJS; faz sentido só com cliente externo.
- **Fontes como `STATE_SNAPSHOT/DELTA`** — adiado por escopo; o bloco único no
  fim continua.
```

- [ ] **Step 2: Registrar no índice de ADRs**

Em `docs/adr/README.md`, alterar a linha do 0009 e acrescentar o 0019 depois do 0018:

```markdown
| [0009](0009-streaming-sse.md) | Streaming das respostas do chat via SSE | *contrato substituído pelo 0019 (transporte SSE mantido)* |
```

```markdown
| [0019](0019-contrato-ag-ui-do-turno.md) | O turno do oráculo é entregue como eventos AG-UI | Aceito |
```

- [ ] **Step 3: Atualizar o CLAUDE.md**

Na seção "Stack principal", logo após o bullet **Agente de IA**, acrescentar:

```markdown
- **Protocolo de UI:** o turno é entregue ao cliente como eventos **AG-UI** (Agent–User Interaction Protocol) sobre SSE: `POST /conversations/ask` recebe `RunAgentInput` e responde `RUN_STARTED` → `STEP_*`/`TOOL_CALL_*`/`TEXT_MESSAGE_*` → `CUSTOM oracle.sources` → `RUN_FINISHED`. A tradução chunk → evento mora em `src/app/api/streaming/` (pacote `ag-ui-protocol`, só tipos + encoder). **Domínio e grafo não conhecem o protocolo.** Ver ADR-0019.
```

Na lista "ADRs atuais", após a linha do ADR-0018:

```markdown
- **ADR-0019** — O turno do oráculo é entregue como eventos AG-UI (substitui o contrato do 0009; SSE mantido)
```

- [ ] **Step 4: Adicionar a dependência**

Em `pyproject.toml`, dentro de `dependencies`, logo após a linha `"httpx>=0.27",`:

```toml
    # Protocolo AG-UI (ADR-0019): só tipos Pydantic + EventEncoder. A tradução
    # chunk -> evento mora em src/app/api/streaming/; domínio e grafo não importam.
    "ag-ui-protocol>=0.1,<1",
```

Run: `uv lock && uv sync`
Expected: lock atualizado; `uv run python -c "from ag_ui.core import RunAgentInput; from ag_ui.encoder import EventEncoder; print('ok')"` imprime `ok`.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0019-contrato-ag-ui-do-turno.md docs/adr/README.md CLAUDE.md pyproject.toml uv.lock
git commit -m "docs(adr): ADR-0019 — turno entregue como eventos AG-UI; dependência ag-ui-protocol

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `AgentStreamChunk` vira união de dataclasses

**Files:**
- Modify: `src/support/agent/ports.py:20-25`
- Modify: `src/support/agent/graph/runner.py` (usos de `AgentStreamChunk(type=...)`), `src/app/api/controllers/conversation_controller.py:64-72`, `evals/runner.py:22-27`, `tests/fakes/fake_turn_graph.py`, `tests/unit/support/agent/test_ports.py`, `tests/unit/support/agent/test_domain_boundary.py`, `tests/unit/support/agent/graph/test_runner.py`, `tests/unit/evals/test_runner.py`, `tests/unit/domain/conversations/actions/test_answer_question_action.py:107`, `tests/integration/api/test_ask_endpoint.py:27-31`, `tests/integration/api/test_ask_trace_persistence.py:35-39`

**Interfaces:**
- Produces (em `src/support/agent/ports.py`):
  - `TextChunk(text: str)`
  - `SourcesChunk(citations: list[Citation] = [])`
  - `StepChunk(name: str, phase: Literal["started","finished"], detail: dict | None = None)`
  - `ToolCallStartChunk(id: str, name: str)`
  - `ToolCallArgsChunk(id: str, delta: str)`
  - `ToolCallEndChunk(id: str)`
  - `ToolCallResultChunk(id: str, status: Literal["ok","error"])`
  - `AgentStreamChunk` = união dos sete.

- [ ] **Step 1: Reescrever os testes do port**

Substituir os dois primeiros testes de `tests/unit/support/agent/test_ports.py` por:

```python
from src.support.agent.ports import (
    AgentMessage,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)
from src.domain.shared.value_objects.citation import Citation


def test_text_chunk_carries_text():
    assert TextChunk(text="olá").text == "olá"


def test_sources_chunk_defaults_to_no_citations():
    assert SourcesChunk().citations == []
    c = SourcesChunk(citations=[Citation("web", "T", "u", "s")])
    assert len(c.citations) == 1


def test_step_chunk_detail_is_optional():
    started = StepChunk(name="gate", phase="started")
    finished = StepChunk(name="retrieve", phase="finished", detail={"kept": 3})
    assert started.detail is None
    assert finished.detail == {"kept": 3}


def test_tool_call_chunks_are_plain_dataclasses():
    assert ToolCallStartChunk(id="c1", name="web_search").name == "web_search"
    assert ToolCallArgsChunk(id="c1", delta='{"q').delta == '{"q'
    assert ToolCallEndChunk(id="c1").id == "c1"
    assert ToolCallResultChunk(id="c1", status="error").status == "error"
```

(Os demais testes do arquivo — `test_agent_message`, `test_knowledge_snippet_carries_content_and_citation`, etc. — permanecem.)

- [ ] **Step 2: Reforçar o teste de fronteira**

Em `tests/unit/support/agent/test_domain_boundary.py`, acrescentar ao final:

```python
_PROTOCOL = ("ag_ui",)
_SUPPORT_AGENT = _DOMAIN.parent / "support" / "agent"


def _protocol_imports(path: pathlib.Path) -> list[str]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if any(pkg in stripped for pkg in _PROTOCOL):
            hits.append(f"{path}:{lineno}: {stripped}")
    return hits


def test_domain_and_graph_do_not_import_the_ui_protocol():
    """ADR-0019: o AG-UI é assunto da camada app. O port fala em dataclasses
    puras; quem traduz para eventos é src/app/api/streaming/."""
    roots = [_DOMAIN, _SUPPORT_AGENT]
    offenders = [hit for root in roots for py in root.rglob("*.py") for hit in _protocol_imports(py)]
    assert offenders == [], "ag_ui vazou para o domínio ou para o grafo:\n" + "\n".join(offenders)
```

- [ ] **Step 3: Rodar os testes para ver falhar**

Run: `uv run pytest tests/unit/support/agent/test_ports.py tests/unit/support/agent/test_domain_boundary.py -q`
Expected: `test_ports.py` falha com `ImportError: cannot import name 'TextChunk'`; o teste novo de fronteira passa (ainda não há `ag_ui` em lugar nenhum).

- [ ] **Step 4: Implementar a união em `ports.py`**

Substituir, em `src/support/agent/ports.py`, o bloco:

```python
@dataclass
class AgentStreamChunk:
    type: Literal["text", "sources"]
    text: str = ""
    citations: list[Citation] = field(default_factory=list)
```

por:

```python
@dataclass
class TextChunk:
    """Texto do modelo de resposta (ou o texto canônico da recusa)."""

    text: str


@dataclass
class SourcesChunk:
    """Fontes do turno. Sempre o último chunk do stream."""

    citations: list[Citation] = field(default_factory=list)


@dataclass
class StepChunk:
    """Um nó do grafo abriu ou fechou: gate, retrieve, refuse ou answer.

    `detail` só vem no `finished` e só quando há dado útil para a UI
    (ex.: {"kept": 4} do retrieval). Ver ADR-0019.
    """

    name: str
    phase: Literal["started", "finished"]
    detail: dict | None = None


@dataclass
class ToolCallStartChunk:
    id: str
    name: str


@dataclass
class ToolCallArgsChunk:
    """Fragmento do JSON dos argumentos, como o provedor o entrega."""

    id: str
    delta: str


@dataclass
class ToolCallEndChunk:
    id: str


@dataclass
class ToolCallResultChunk:
    """Só o status. O conteúdo que a tool devolveu ao modelo NUNCA passa por
    aqui (regra 4 do CLAUDE.md) — fica no LangSmith."""

    id: str
    status: Literal["ok", "error"]


AgentStreamChunk = (
    TextChunk
    | SourcesChunk
    | StepChunk
    | ToolCallStartChunk
    | ToolCallArgsChunk
    | ToolCallEndChunk
    | ToolCallResultChunk
)
```

- [ ] **Step 5: Adaptar os consumidores mínimos (sem mudar comportamento)**

`src/support/agent/graph/runner.py` — trocar o import e os três construtores:

```python
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    TextChunk,
    TurnDependencies,
    TurnSignals,
)
```

- linha 63: `return TextChunk(text=text) if text else None`
- linha 73: `return TextChunk(text=update["answer"])`
- linha 236: `yield SourcesChunk(citations=collected["citations"])`

`src/app/api/controllers/conversation_controller.py` — import e o laço:

```python
from src.support.agent.ports import SourcesChunk, TextChunk
```

```python
                async for chunk in stream:
                    if isinstance(chunk, TextChunk):
                        captured["text"] += chunk.text
                        yield _sse("token", {"text": chunk.text})
                    elif isinstance(chunk, SourcesChunk):
                        captured["citations"] = chunk.citations
                        yield _sse(
                            "sources",
                            {"citations": [_citation_payload(c) for c in chunk.citations]},
                        )
```

`evals/runner.py`:

```python
from src.support.agent.ports import AgentMessage, KnowledgeSnippet, TextChunk, TurnDependencies, TurnSignals
```

```python
async def _collect_text(stream) -> str:
    text = ""
    async for chunk in stream:
        if isinstance(chunk, TextChunk):
            text += chunk.text
    return text
```

`tests/fakes/fake_turn_graph.py`:

```python
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
)
```

```python
    async def _stream(self) -> AsyncIterator[AgentStreamChunk]:
        # Um passo "answer" em volta do texto, para os testes de integração
        # exercitarem a tradução de passos além de texto e fontes.
        yield StepChunk(name="answer", phase="started")
        for token in self._answer.split():
            yield TextChunk(text=token + " ")
        yield StepChunk(name="answer", phase="finished")
        cites = [] if self._outcome == "refusal" else self._citations
        yield SourcesChunk(citations=cites)
```

`tests/unit/evals/test_runner.py` — import e o `_stream` do `_FakeGraph`:

```python
from src.support.agent.ports import SourcesChunk, TextChunk
```

```python
    async def _stream(self):
        yield TextChunk(text=self._answer)
        yield SourcesChunk(citations=[])
```

`tests/unit/domain/conversations/actions/test_answer_question_action.py` — adicionar `from src.support.agent.ports import TextChunk` ao import de ports e trocar a linha 107:

```python
    assert any(isinstance(c, TextChunk) for c in chunks)
```

`tests/integration/api/test_ask_endpoint.py` e `tests/integration/api/test_ask_trace_persistence.py` — no `_FailingTurnGraph._stream`:

```python
            from src.support.agent.ports import TextChunk

            yield TextChunk(text="ola ")
```

`tests/unit/support/agent/graph/test_runner.py` — adicionar `SourcesChunk, TextChunk` ao import de `src.support.agent.ports` e trocar:

- linhas 116–117: `assert isinstance(chunks[-1], SourcesChunk)` e manter a asserção dos títulos.
- linhas 128, 143, 321: `"".join(c.text for c in chunks if isinstance(c, TextChunk))`
- linha 146: `assert isinstance(chunks[-1], SourcesChunk)`
- linhas 200–202 (classe `Test_token_chunk`): `assert isinstance(chunk, TextChunk)` e `assert chunk.text == "olá"`.

- [ ] **Step 6: Rodar a suíte unitária**

Run: `uv run pytest tests/unit -q`
Expected: tudo verde (os testes de integração são exercitados na Task 8).

- [ ] **Step 7: Commit**

```bash
git add src/support/agent/ports.py src/support/agent/graph/runner.py src/app/api/controllers/conversation_controller.py evals/runner.py tests/
git commit -m "refactor(agent): AgentStreamChunk vira união de dataclasses (texto, fontes, passos, tool calls)

Prepara o ADR-0019. Comportamento inalterado: runner e controller ainda só
emitem texto e fontes. Teste de fronteira passa a barrar ag_ui em domain/ e
support/agent/.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Runner emite passos e acumula a fase 1 numa lista

**Files:**
- Modify: `src/support/agent/graph/runner.py` (reescrita)
- Test: `tests/unit/support/agent/graph/test_runner.py`

**Interfaces:**
- Produces (em `runner.py`): `class TurnEmitter(signals)` com `on_update(payload: dict) -> list[AgentStreamChunk]`, `on_message(payload: tuple) -> list[AgentStreamChunk]`, `finish() -> list[AgentStreamChunk]`, `step_started(name)`, `step_finished(name)`, atributo `citations`. `_token_chunk` deixa de existir.
- Consumes: os chunks da Task 2.

- [ ] **Step 1: Escrever os testes de passos**

Em `tests/unit/support/agent/graph/test_runner.py`, trocar o import do runner por `from src.support.agent.graph.runner import TurnEmitter, TurnGraphRunner`, adicionar `StepChunk` ao import de ports, e acrescentar:

```python
def _steps(chunks):
    return [(c.name, c.phase) for c in chunks if isinstance(c, StepChunk)]


@pytest.mark.asyncio
async def test_steps_are_emitted_in_pipeline_order_with_their_details():
    signals = TurnSignals()
    stream = await _runner().start(
        "o que é PSP?", [], _deps(_RecordingSearch([_snippet()])), signals, extra_config=_models()
    )
    chunks = await _drain(stream)

    assert _steps(chunks) == [
        ("gate", "started"),
        ("gate", "finished"),
        ("retrieve", "started"),
        ("retrieve", "finished"),
        ("answer", "started"),
        ("answer", "finished"),
    ]
    by_name = {c.name: c for c in chunks if isinstance(c, StepChunk) and c.phase == "finished"}
    assert by_name["gate"].detail == {"retrieve": True, "degraded": False}
    assert by_name["retrieve"].detail == {"kept": 1}
    assert by_name["answer"].detail is None
    # o passo answer fecha logo antes das fontes, nunca antes do último texto
    assert isinstance(chunks[-1], SourcesChunk)
    assert chunks[-2] == StepChunk(name="answer", phase="finished")


@pytest.mark.asyncio
async def test_a_refusal_emits_the_refuse_step_before_its_text_and_no_answer_step():
    stream = await _runner().start(
        "quanto custa um carro?", [], _deps(_RecordingSearch([])), TurnSignals(), extra_config=_models()
    )
    chunks = await _drain(stream)

    assert _steps(chunks) == [
        ("gate", "started"),
        ("gate", "finished"),
        ("retrieve", "started"),
        ("retrieve", "finished"),
        ("refuse", "started"),
        ("refuse", "finished"),
    ]
    refuse_at = next(i for i, c in enumerate(chunks) if isinstance(c, StepChunk) and c.name == "refuse" and c.phase == "finished")
    first_text_at = next(i for i, c in enumerate(chunks) if isinstance(c, TextChunk))
    assert refuse_at < first_text_at


@pytest.mark.asyncio
async def test_preset_knowledge_emits_only_the_answer_step():
    stream = await _runner().start(
        "resuma", [], _deps(_RecordingSearch([])), TurnSignals(),
        knowledge=[_snippet()], extra_config=_models(),
    )
    chunks = await _drain(stream)

    assert _steps(chunks) == [("answer", "started"), ("answer", "finished")]


@pytest.mark.asyncio
async def test_the_answer_step_opens_and_closes_once_even_with_a_tool_loop():
    executed = {"ran": False}
    runner = TurnGraphRunner(graph=_tool_loop_graph(executed), enable_tools=False)
    stream = await runner.start(
        "o que é PSP?", [], _deps(_RecordingSearch([_snippet()])), TurnSignals(),
        knowledge=[_snippet()], extra_config={"answer_model": _ToolCallingModel()},
    )
    chunks = await _drain(stream)

    assert _steps(chunks) == [("answer", "started"), ("answer", "finished")]


@pytest.mark.asyncio
async def test_phase_one_buffers_every_chunk_it_produced():
    """Os passos de gate e retrieve nascem durante o `await start()`; a fase 2
    tem que reproduzi-los antes de qualquer token, na ordem."""
    stream = await _runner().start(
        "o que é PSP?", [], _deps(_RecordingSearch([_snippet()])), TurnSignals(),
        extra_config=_models(answer=_ChatModel("PSP é um programa")),
    )
    chunks = await _drain(stream)

    first_text_at = next(i for i, c in enumerate(chunks) if isinstance(c, TextChunk))
    assert _steps(chunks[:first_text_at]) == [
        ("gate", "started"), ("gate", "finished"),
        ("retrieve", "started"), ("retrieve", "finished"),
        ("answer", "started"),
    ]
```

Substituir a classe `Test_token_chunk` inteira por:

```python
class TestTurnEmitterOnMessage:
    """stream_mode="messages" emite QUALQUER mensagem nova de QUALQUER nó —
    inclusive a ToolMessage que o ToolNode devolve, com conteúdo bruto em
    <<TOOL_CONTENT>>. Só texto do nó de resposta vira TextChunk."""

    def test_a_tool_message_never_becomes_text(self):
        emitter = TurnEmitter(TurnSignals())
        payload = (
            ToolMessage(content="<<TOOL_CONTENT>>\nsegredo do tool\n<</TOOL_CONTENT>>", tool_call_id="x"),
            {"langgraph_node": "tools"},
        )

        assert emitter.on_message(payload) == []

    def test_an_ai_message_from_the_answer_node_opens_the_step_and_yields_text(self):
        emitter = TurnEmitter(TurnSignals())
        payload = (AIMessage(content="olá"), {"langgraph_node": "answer"})

        chunks = emitter.on_message(payload)

        assert chunks == [StepChunk(name="answer", phase="started"), TextChunk(text="olá")]
        # segunda mensagem do mesmo nó: o passo não reabre
        assert emitter.on_message((AIMessage(content=" mundo"), {"langgraph_node": "answer"})) == [
            TextChunk(text=" mundo")
        ]

    def test_an_ai_message_from_another_node_is_ignored(self):
        emitter = TurnEmitter(TurnSignals())

        assert emitter.on_message((AIMessage(content="x"), {"langgraph_node": "gate"})) == []
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/unit/support/agent/graph/test_runner.py -q`
Expected: FAIL com `ImportError: cannot import name 'TurnEmitter'`.

- [ ] **Step 3: Reescrever `runner.py`**

Conteúdo completo de `src/support/agent/graph/runner.py`:

```python
"""Consumo do grafo em DUAS FASES — ver spec, seção 5.

`BaseHTTPMiddleware` devolve `call_next` quando o StreamingResponse é
*construído*; o corpo SSE é gerado depois, já fora do `async with` que mantém a
sessão async. Logo os nós que tocam o banco (gate, retrieve) precisam rodar
durante o `await start()`, dentro do escopo do request.

`start()` dirige o grafo até a ENTRADA do nó de resposta e devolve o gerador do
restante. Dali em diante só há token de LLM e tool HTTP — a mesma invariante que
o motor anterior mantinha por convenção, agora explícita na estrutura.

Desde o ADR-0019 o runner não esconde mais o que o grafo faz entre a pergunta e
o texto: cada nó vira um `StepChunk`. A tradução para eventos AG-UI NÃO é daqui
— mora em `src/app/api/streaming/`. Este módulo só fala em dataclasses do port.
"""

import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
    TurnDependencies,
    TurnSignals,
)

_CITATION_NODES = ("answer", "refuse")


def _text_of(message) -> str:
    """Anthropic entrega blocos, OpenAI entrega string."""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content


def _is_answer_event(payload) -> bool:
    """O evento veio do nó de resposta? É o que encerra a fase 1 (revisão I4)."""
    _, metadata = payload
    return metadata.get("langgraph_node") == "answer"


def _step_detail(name: str, signals: TurnSignals) -> dict | None:
    """O que a UI mostra ao lado do passo. Lido dos `signals`, que o nó já
    escreveu quando o seu update chega."""
    if name == "gate":
        return {"retrieve": signals.gate_retrieve, "degraded": signals.gate_degraded}
    if name == "retrieve":
        return {"kept": signals.retrieval_kept}
    return None


class TurnEmitter:
    """Traduz os eventos brutos do LangGraph (`updates` e `messages`) em chunks
    do port, guardando o pouco de estado que isso exige: quais passos já
    abriram e as citações coletadas. Um por run.

    `updates` chega no FIM de cada nó, por isso o `started` de um passo é
    sintetizado no primeiro sinal do nó — o próprio update, ou (só para
    `answer`) o primeiro evento de `messages` vindo dele.
    """

    def __init__(self, signals: TurnSignals) -> None:
        self._signals = signals
        self._steps_started: set[str] = set()
        self.citations: list[Citation] = []

    def step_started(self, name: str) -> list[AgentStreamChunk]:
        if name in self._steps_started:
            return []
        self._steps_started.add(name)
        return [StepChunk(name=name, phase="started")]

    def step_finished(self, name: str) -> list[AgentStreamChunk]:
        return [
            *self.step_started(name),
            StepChunk(name=name, phase="finished", detail=_step_detail(name, self._signals)),
        ]

    def on_update(self, payload: dict) -> list[AgentStreamChunk]:
        """Um payload de stream_mode="updates": {nó: saída do nó}."""
        out: list[AgentStreamChunk] = []
        for node, update in payload.items():
            update = update or {}
            if node in ("gate", "retrieve"):
                out += self.step_finished(node)
            elif node == "refuse":
                # O nó refuse é determinístico: não passa por LLM, então nunca
                # aparece em "messages". O texto chega por aqui e o chunk é
                # sintetizado — é o que mantém a recusa instantânea.
                out += self.step_finished("refuse")
                if update.get("answer"):
                    out.append(TextChunk(text=update["answer"]))
            elif node == "answer":
                out += self.step_started("answer")
            if node in _CITATION_NODES and update.get("citations") is not None:
                self.citations = list(update["citations"])
        return out

    def on_message(self, payload) -> list[AgentStreamChunk]:
        """Um payload de stream_mode="messages": (mensagem, metadata).

        Só o nó `answer` interessa, e dele só texto de AIMessage/AIMessageChunk:
        a ToolMessage que o ToolNode devolve (conteúdo bruto em <<TOOL_CONTENT>>)
        e o próprio prompt (System/Human) que o nó devolve no state nunca viram
        texto. Preâmbulo antes de uma tool call continua passando.
        """
        message, _ = payload
        if not _is_answer_event(payload):
            return []
        out = self.step_started("answer")
        if not isinstance(message, (AIMessage, AIMessageChunk)):
            return out
        text = _text_of(message)
        if text:
            out.append(TextChunk(text=text))
        return out

    def finish(self) -> list[AgentStreamChunk]:
        """Fim do stream: fecha o passo de resposta (se abriu) e entrega as fontes."""
        out: list[AgentStreamChunk] = []
        if "answer" in self._steps_started:
            out.append(StepChunk(name="answer", phase="finished"))
        out.append(SourcesChunk(citations=list(self.citations)))
        return out


def _mark_first_token(signals: TurnSignals) -> None:
    """Primeiro TEXTO vindo do nó de resposta, contado desde a entrada nesse nó.

    Fora do caminho de resposta (`answer_started_at is None`, isto é: recusa)
    nada é marcado — a recusa é texto canônico e não entra nas médias do motor.
    """
    if signals.answer_started_at is None or signals.first_token_ms is not None:
        return
    signals.first_token_ms = int((time.monotonic() - signals.answer_started_at) * 1000)


def _mark_engine_end(signals: TurnSignals) -> None:
    """Fim do stream: total do estágio de resposta (inclui o tool loop)."""
    if signals.answer_started_at is None:
        return
    signals.engine_ms = int((time.monotonic() - signals.answer_started_at) * 1000)


def _initial_state(
    question: str, history: list[AgentMessage], knowledge: list[KnowledgeSnippet] | None
) -> dict:
    """`preset_knowledge` liga a aresta que pula gate/retrieve (eval adversarial)."""
    return {
        "question": question,
        "history": history,
        "knowledge": list(knowledge) if knowledge is not None else [],
        "preset_knowledge": knowledge is not None,
        "messages": [],
    }


class TurnGraphRunner:
    def __init__(
        self,
        graph=None,
        enable_tools: bool = True,
        run_id: str | None = None,
        user_hash: str | None = None,
    ) -> None:
        self._graph = graph or TURN_GRAPH
        self._enable_tools = enable_tools
        self._run_id = run_id
        self._user_hash = user_hash

    def _config(self, deps: TurnDependencies, signals: TurnSignals, extra_config: dict | None) -> dict:
        config: dict = {
            "configurable": {
                "deps": deps,
                "signals": signals,
                "citations": [],
                "enable_tools": self._enable_tools,
                **(extra_config or {}),
            }
        }
        # run_id/metadata ficam no TOPO do config (contrato do LangGraph/LangSmith),
        # não em "configurable". O e-mail em claro nunca entra aqui — só o hash.
        if self._run_id is not None:
            config["run_id"] = self._run_id
        if self._user_hash is not None:
            config["metadata"] = {"user_hash": self._user_hash}
        return config

    async def start(
        self,
        question: str,
        history: list[AgentMessage],
        deps: TurnDependencies,
        signals: TurnSignals,
        knowledge: list[KnowledgeSnippet] | None = None,
        extra_config: dict | None = None,
    ) -> AsyncIterator[AgentStreamChunk]:
        emitter = TurnEmitter(signals)
        agen = self._graph.astream(
            _initial_state(question, history, knowledge),
            stream_mode=["updates", "messages"],
            config=self._config(deps, signals, extra_config),
        )

        # FASE 1 — sessão viva. Para na ENTRADA do nó de resposta (revisão I4).
        #
        # O critério NÃO é "o primeiro texto": quando o modelo abre com uma
        # AIMessage só de tool_calls (content vazio — a forma comum de
        # Anthropic/OpenAI), nenhum chunk de texto é produzido e o laço
        # answer -> tools -> answer inteiro rodaria aqui dentro, segurando a
        # conexão Postgres do request durante chamadas HTTP externas. O critério
        # é o PRIMEIRO evento "messages" do nó `answer` — mesmo que ele não
        # renda texto.
        #
        # Tudo que a fase 1 produz (passos de gate/retrieve, o refuse com seu
        # texto, o `answer started`, o primeiro token se houver) vai para
        # `buffered`; a fase 2 reproduz a lista antes de continuar.
        buffered: list[AgentStreamChunk] = []
        deferred: Exception | None = None
        try:
            async for mode, payload in agen:
                if mode == "updates":
                    buffered += emitter.on_update(payload)
                    if "refuse" in payload:
                        break
                    continue
                if not _is_answer_event(payload):
                    continue
                chunks = emitter.on_message(payload)
                if any(isinstance(c, TextChunk) for c in chunks):
                    _mark_first_token(signals)
                buffered += chunks
                break
        except Exception as exc:
            # Revisão I3 — de onde veio a falha decide quem a trata:
            #
            # - gate/retrieve/refuse (`answer_started_at is None`): sobe agora,
            #   ainda dentro da sessão, e o rollback do DBSessionMiddleware pega
            #   (spec, seção 7). Turno sem contexto é pior que erro visível.
            # - estágio de resposta (o nó `answer` já foi carimbado): a exceção
            #   é ADIADA para o `_resume`. Se subisse aqui, viraria um 500 seco:
            #   o middleware faria rollback (perdendo a mensagem do usuário) e
            #   NENHUMA linha de agent_traces com outcome="error" seria gravada
            #   — justamente o trace mais valioso. Adiando, cai no `except` que
            #   o controller já tem: RUN_ERROR + trace persistido, com a
            #   mensagem do usuário já commitada.
            if signals.answer_started_at is None:
                raise
            deferred = exc

        # FASE 2 — devolvida ao controller, consumida fora do escopo da sessão.
        return _resume(buffered, agen, emitter, signals, deferred)


async def _resume(
    buffered: list[AgentStreamChunk],
    agen,
    emitter: TurnEmitter,
    signals: TurnSignals,
    deferred: Exception | None = None,
) -> AsyncIterator[AgentStreamChunk]:
    # Primeira coisa: relançar a falha do estágio de resposta capturada na fase 1
    # (revisão I3), para que ela chegue ao `except` do controller.
    if deferred is not None:
        raise deferred
    for chunk in buffered:
        yield chunk
    async for mode, payload in agen:
        chunks = emitter.on_update(payload) if mode == "updates" else emitter.on_message(payload)
        for chunk in chunks:
            if isinstance(chunk, TextChunk):
                _mark_first_token(signals)
            yield chunk
    _mark_engine_end(signals)
    for chunk in emitter.finish():
        yield chunk


def get_turn_graph_runner(
    enable_tools: bool = True,
    run_id: str | None = None,
    user_hash: str | None = None,
) -> "TurnGraphRunner":
    return TurnGraphRunner(enable_tools=enable_tools, run_id=run_id, user_hash=user_hash)
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/unit/support/agent/graph/test_runner.py tests/unit/evals -q`
Expected: PASS — inclusive os testes antigos da invariante (`test_gate_and_retrieval_run_before_the_generator_is_handed_off`, `test_phase_one_stops_at_the_answer_node_even_without_any_text`, latências, falhas adiadas).

- [ ] **Step 5: Commit**

```bash
git add src/support/agent/graph/runner.py tests/unit/support/agent/graph/test_runner.py
git commit -m "feat(agent): runner emite StepChunk por nó e acumula a fase 1 numa lista

TurnEmitter concentra a tradução updates/messages -> chunks. Passos gate,
retrieve, refuse e answer com detalhe lido dos signals; answer abre e fecha
uma vez mesmo com tool loop. Invariante das duas fases inalterada.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Runner emite tool calls (start/args/end/result)

**Files:**
- Modify: `src/support/agent/graph/runner.py` (`TurnEmitter`)
- Test: `tests/unit/support/agent/graph/test_runner.py`

**Interfaces:**
- Consumes: `ToolCallStartChunk`, `ToolCallArgsChunk`, `ToolCallEndChunk`, `ToolCallResultChunk` (Task 2); `TurnEmitter` (Task 3).
- Produces: `TurnEmitter` passa a emitir tool calls a partir de `tool_call_chunks`/`tool_calls` (messages) e de `ToolMessage` (update do nó `tools`).

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/unit/support/agent/graph/test_runner.py` (importar `AIMessageChunk` de `langchain_core.messages` e os quatro chunks de tool call de `src.support.agent.ports`):

```python
def _tool_chunks(chunks):
    return [
        c for c in chunks
        if isinstance(c, (ToolCallStartChunk, ToolCallArgsChunk, ToolCallEndChunk, ToolCallResultChunk))
    ]


@pytest.mark.asyncio
async def test_a_whole_tool_call_becomes_start_args_end_then_result():
    """Provedor sem streaming (ou fake): a AIMessage chega inteira com
    `tool_calls`. O runner emite a sequência completa de uma vez e, quando o
    ToolNode devolve, o result — só com status, nunca o conteúdo."""
    executed = {"ran": False}
    runner = TurnGraphRunner(graph=_tool_loop_graph(executed), enable_tools=False)
    stream = await runner.start(
        "o que é PSP?", [], _deps(_RecordingSearch([_snippet()])), TurnSignals(),
        knowledge=[_snippet()], extra_config={"answer_model": _ToolCallingModel()},
    )
    chunks = await _drain(stream)

    assert _tool_chunks(chunks) == [
        ToolCallStartChunk(id="call-1", name="fake_tool"),
        ToolCallArgsChunk(id="call-1", delta='{"query": "psp"}'),
        ToolCallEndChunk(id="call-1"),
        ToolCallResultChunk(id="call-1", status="ok"),
    ]
    assert not any("resultado da tool" in c.text for c in chunks if isinstance(c, TextChunk))
    # ordem relativa: o result vem antes do texto final, e o texto antes de answer/finished
    result_at = next(i for i, c in enumerate(chunks) if isinstance(c, ToolCallResultChunk))
    final_text_at = next(i for i, c in enumerate(chunks) if isinstance(c, TextChunk) and "resposta final" in c.text)
    assert result_at < final_text_at


class TestTurnEmitterToolCalls:
    def test_streamed_fragments_become_one_start_and_args_deltas(self):
        """Anthropic/OpenAI mandam id+nome no primeiro fragmento e só `index`
        nos seguintes. O runner resolve index -> id e não duplica o start."""
        emitter = TurnEmitter(TurnSignals())
        meta = {"langgraph_node": "answer"}
        first = AIMessageChunk(content="", tool_call_chunks=[
            {"name": "web_search", "args": "", "id": "call_1", "index": 0, "type": "tool_call_chunk"},
        ])
        second = AIMessageChunk(content="", tool_call_chunks=[
            {"name": None, "args": '{"qu', "id": None, "index": 0, "type": "tool_call_chunk"},
        ])
        third = AIMessageChunk(content="", tool_call_chunks=[
            {"name": None, "args": 'ery":"psp"}', "id": None, "index": 0, "type": "tool_call_chunk"},
        ])

        out = emitter.on_message((first, meta)) + emitter.on_message((second, meta)) + emitter.on_message((third, meta))

        assert [c for c in out if not isinstance(c, StepChunk)] == [
            ToolCallStartChunk(id="call_1", name="web_search"),
            ToolCallArgsChunk(id="call_1", delta='{"qu'),
            ToolCallArgsChunk(id="call_1", delta='ery":"psp"}'),
        ]

    def test_the_answer_update_closes_pending_tool_calls_once(self):
        emitter = TurnEmitter(TurnSignals())
        meta = {"langgraph_node": "answer"}
        emitter.on_message((AIMessageChunk(content="", tool_call_chunks=[
            {"name": "web_search", "args": '{"query":"psp"}', "id": "call_1", "index": 0, "type": "tool_call_chunk"},
        ]), meta))
        final = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "psp"}, "id": "call_1"}])

        out = emitter.on_update({"answer": {"messages": [final], "citations": []}})

        assert out == [ToolCallEndChunk(id="call_1")]
        # o update do nó tools não reabre nem refecha
        result = emitter.on_update({"tools": {"messages": [
            ToolMessage(content="<<TOOL_CONTENT>>\nresultado\n<</TOOL_CONTENT>>", tool_call_id="call_1", name="web_search"),
        ]}})
        assert result == [ToolCallResultChunk(id="call_1", status="ok")]

    def test_a_tool_failure_wrapped_by_tools_py_becomes_status_error(self):
        emitter = TurnEmitter(TurnSignals())
        emitter.on_message((AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c9"}]), {"langgraph_node": "answer"}))

        out = emitter.on_update({"tools": {"messages": [
            ToolMessage(content="<<TOOL_CONTENT>>\n(falha ao buscar na web: timeout)\n<</TOOL_CONTENT>>", tool_call_id="c9", name="web_search"),
        ]}})

        assert out == [ToolCallResultChunk(id="c9", status="error")]

    def test_a_tool_message_with_error_status_becomes_status_error(self):
        emitter = TurnEmitter(TurnSignals())
        emitter.on_message((AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c9"}]), {"langgraph_node": "answer"}))

        out = emitter.on_update({"tools": {"messages": [
            ToolMessage(content="Error: boom", tool_call_id="c9", name="web_search", status="error"),
        ]}})

        assert out == [ToolCallResultChunk(id="c9", status="error")]

    def test_a_result_for_an_unknown_call_still_reports_status(self):
        """Se por algum motivo o start não foi visto, o result ainda sai — a UI
        ignora ids desconhecidos, mas o encoder não pode perder o evento."""
        emitter = TurnEmitter(TurnSignals())

        out = emitter.on_update({"tools": {"messages": [
            ToolMessage(content="ok", tool_call_id="ghost", name="web_search"),
        ]}})

        assert out == [ToolCallResultChunk(id="ghost", status="ok")]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/unit/support/agent/graph/test_runner.py -q -k "tool"`
Expected: FAIL — `_tool_chunks(chunks) == []` e os testes do emitter não encontram tool chunks.

- [ ] **Step 3: Implementar em `runner.py`**

Imports — trocar por:

```python
import json
import time
from typing import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.builder import TURN_GRAPH
from src.support.agent.ports import (
    AgentMessage,
    AgentStreamChunk,
    KnowledgeSnippet,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
    TurnDependencies,
    TurnSignals,
)

_CITATION_NODES = ("answer", "refuse")
_TOOL_CONTENT_OPEN = "<<TOOL_CONTENT>>"
_TOOL_CONTENT_CLOSE = "<</TOOL_CONTENT>>"
# tools.py devolve falha capturada como texto "(falha ao ...)" dentro do envelope.
_TOOL_FAILURE_PREFIX = "(falha"
```

Nova função de módulo, após `_step_detail`:

```python
def _tool_status(message: ToolMessage) -> str:
    """Só o status atravessa o port. O conteúdo em si fica no LangSmith (regra 4)."""
    if getattr(message, "status", "success") == "error":
        return "error"
    text = _text_of(message).strip()
    if text.startswith(_TOOL_CONTENT_OPEN):
        text = text[len(_TOOL_CONTENT_OPEN):].strip()
    if text.endswith(_TOOL_CONTENT_CLOSE):
        text = text[: -len(_TOOL_CONTENT_CLOSE)].strip()
    return "error" if text.startswith(_TOOL_FAILURE_PREFIX) else "ok"
```

Em `TurnEmitter.__init__`, acrescentar:

```python
        self._tool_started: set[str] = set()
        self._tool_ended: set[str] = set()
        self._index_to_id: dict[int, str] = {}
```

Em `TurnEmitter.on_update`, trocar os dois ramos:

```python
            elif node == "answer":
                out += self.step_started("answer")
                out += self._tool_ends_from(update)
            elif node == "tools":
                out += self._tool_results_from(update)
```

Em `TurnEmitter.on_message`, entre a checagem de `isinstance` e o texto:

```python
        out += self._tool_calls_from(message)
        text = _text_of(message)
```

Métodos novos em `TurnEmitter` (antes de `finish`):

```python
    # --- tool calls -------------------------------------------------------

    def _tool_start(self, tc_id: str, name: str) -> list[AgentStreamChunk]:
        if tc_id in self._tool_started:
            return []
        self._tool_started.add(tc_id)
        return [ToolCallStartChunk(id=tc_id, name=name)]

    def _tool_end(self, tc_id: str) -> list[AgentStreamChunk]:
        if tc_id not in self._tool_started or tc_id in self._tool_ended:
            return []
        self._tool_ended.add(tc_id)
        return [ToolCallEndChunk(id=tc_id)]

    def _tool_calls_from(self, message) -> list[AgentStreamChunk]:
        """Tool calls de uma mensagem do modelo, em duas formas:

        - fragmentos (`tool_call_chunks`, provedor em streaming): id+nome no
          primeiro, só `index` nos seguintes — o mapa index -> id resolve;
        - a chamada inteira (`tool_calls`, provedor sem streaming ou fake de
          teste): start, args com o JSON completo e end de uma vez.
        """
        out: list[AgentStreamChunk] = []
        fragments = getattr(message, "tool_call_chunks", None) or []
        if fragments:
            for frag in fragments:
                tc_id = frag.get("id")
                index = frag.get("index")
                if tc_id and index is not None:
                    self._index_to_id[index] = tc_id
                if not tc_id and index is not None:
                    tc_id = self._index_to_id.get(index)
                if not tc_id:
                    continue
                if frag.get("name"):
                    out += self._tool_start(tc_id, frag["name"])
                if tc_id in self._tool_started and frag.get("args"):
                    out.append(ToolCallArgsChunk(id=tc_id, delta=frag["args"]))
            return out
        for call in getattr(message, "tool_calls", None) or []:
            tc_id = call.get("id")
            if not tc_id or tc_id in self._tool_started:
                continue
            out += self._tool_start(tc_id, call.get("name") or "")
            out.append(ToolCallArgsChunk(id=tc_id, delta=json.dumps(call.get("args") or {}, ensure_ascii=False)))
            out += self._tool_end(tc_id)
        return out

    def _tool_ends_from(self, update: dict) -> list[AgentStreamChunk]:
        """Update do nó answer: a AIMessage final fecha as tool calls que ainda
        estão abertas. Passa antes por `_tool_calls_from` porque, sem streaming,
        a chamada pode estar aparecendo aqui pela primeira vez."""
        out: list[AgentStreamChunk] = []
        for message in update.get("messages") or []:
            if not isinstance(message, AIMessage):
                continue
            out += self._tool_calls_from(message)
            for call in message.tool_calls or []:
                if call.get("id"):
                    out += self._tool_end(call["id"])
        return out

    def _tool_results_from(self, update: dict) -> list[AgentStreamChunk]:
        """Update do nó tools: uma ToolMessage por chamada executada."""
        out: list[AgentStreamChunk] = []
        for message in update.get("messages") or []:
            if not isinstance(message, ToolMessage):
                continue
            out += self._tool_end(message.tool_call_id)
            out.append(ToolCallResultChunk(id=message.tool_call_id, status=_tool_status(message)))
        return out
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/unit/support/agent -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/support/agent/graph/runner.py tests/unit/support/agent/graph/test_runner.py
git commit -m "feat(agent): runner emite tool calls (start/args/end/result) sem conteúdo de tool

Fragmentos de streaming resolvidos por index -> id; chamada inteira vira a
sequência completa; ToolMessage vira result só com status (regra 4).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `AnswerQuestionAction` faz find-or-create por id

**Files:**
- Modify: `src/domain/conversations/actions/answer_question_action.py:64-88`
- Modify: `src/app/api/controllers/conversation_controller.py:51-53` (cola temporária)
- Test: `tests/unit/domain/conversations/actions/test_answer_question_action.py`

**Interfaces:**
- Produces: `AnswerQuestionAction.execute(question: str, conversation_id: UUID, user_email: str | None) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]` — `conversation_id` obrigatório; desconhecido → cria com esse id; de outro usuário → `NotFoundError`.

- [ ] **Step 1: Ajustar os testes da Action**

Em `tests/unit/domain/conversations/actions/test_answer_question_action.py`:

Substituir `test_new_conversation_persists_user_and_sets_title` por:

```python
@pytest.mark.asyncio
async def test_unknown_conversation_id_creates_the_conversation_with_that_id():
    """ADR-0019: o threadId vem do cliente. Se não existe, a conversa nasce com
    ESSE id — nunca com um novo — para o cliente conseguir continuar o fio."""
    graph, conv_repo, msg_repo = FakeTurnGraph(), _FakeConvRepo(), _FakeMsgRepo()
    action = _make(graph, _FakeSearch(), conv_repo, msg_repo)
    given = uuid4()

    conversation_id, stream, _ = await action.execute("qual o onboarding?", given, "a@x.com")

    assert conv_repo.created is not None
    assert conv_repo.created.uuid == given
    assert conversation_id == given
    assert conv_repo.created.title == "qual o onboarding?"
    assert conv_repo.created.user_email == "a@x.com"
    assert msg_repo.appended[0].role == "user"
    assert msg_repo.appended[0].content == "qual o onboarding?"
    chunks = [c async for c in stream]
    assert any(isinstance(c, TextChunk) for c in chunks)
```

Remover `test_missing_conversation_id_raises_not_found` (não existe mais "não encontrado": desconhecido cria).

Acrescentar:

```python
@pytest.mark.asyncio
async def test_known_conversation_id_is_reused_not_recreated():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    existing = Conversation(uuid4(), "a@x.com", "T", now, now, None)
    conv_repo = _FakeConvRepo(existing=existing)
    action = _make(FakeTurnGraph(), _FakeSearch(), conv_repo, _FakeMsgRepo())

    conversation_id, stream, _ = await action.execute("segunda pergunta", existing.uuid, "a@x.com")
    [c async for c in stream]

    assert conv_repo.created is None
    assert conversation_id == existing.uuid
```

Nas chamadas restantes que passam `None` como `conversation_id` (`test_long_question_title_is_truncated_to_80_chars`, `test_signals_is_the_same_object_the_graph_receives`, `test_action_wires_turn_dependencies_with_a_working_nearest_adapter`), trocar `None` por `uuid4()`.

`test_mismatched_owner_propagates_not_found` permanece igual (404 continua sendo a regra).

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/unit/domain/conversations/actions/test_answer_question_action.py -q`
Expected: FAIL em `test_unknown_conversation_id_creates_the_conversation_with_that_id` (hoje lança `NotFoundError`).

- [ ] **Step 3: Implementar**

Em `answer_question_action.py`, substituir a assinatura e o bloco de resolução da conversa:

```python
    async def execute(
        self, question: str, conversation_id: UUID, user_email: str | None
    ) -> tuple[UUID, AsyncIterator[AgentStreamChunk], TurnTraceDraft]:
        now = datetime.now(timezone.utc)
        draft = TurnTraceDraft(question=question, user_email=user_email)

        # ADR-0019: o id vem do cliente (threadId do AG-UI). Conhecido e do
        # usuário → continua; desconhecido → nasce com ESSE id; de outro
        # usuário → a policy responde 404 (nunca revela que existe).
        conversation = await self.conversations.get_by_id(conversation_id)
        if conversation is None:
            conversation = await self.conversations.create(
                Conversation(
                    uuid=conversation_id,
                    user_email=user_email,
                    title=question[:_TITLE_MAX],
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        else:
            ConversationAccessPolicy.assert_can_access(conversation, user_email)
```

Manter `from uuid6 import uuid7` (a `Message` do usuário continua nascendo com `uuid7()`). Remover `from src.support.core.exceptions import NotFoundError`: o único uso era o `raise` que saiu.

Cola temporária no controller (será substituída na Task 8) — em `conversation_controller.py`:

```python
from uuid6 import uuid7
```

```python
        conversation_id, stream, draft = await action.execute(
            data.question, data.conversation_id or uuid7(), user_email
        )
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/unit/domain -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/domain/conversations/actions/answer_question_action.py src/app/api/controllers/conversation_controller.py tests/unit/domain/conversations/actions/test_answer_question_action.py
git commit -m "feat(conversations): AnswerQuestionAction faz find-or-create pelo id da conversa

Preparação para o threadId do AG-UI (ADR-0019). Conversa alheia segue 404.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: `RunAgentRequest` — o body do endpoint

**Files:**
- Create: `src/app/api/requests/run_agent_request.py`, `tests/unit/app/api/requests/__init__.py`, `tests/unit/app/api/requests/test_run_agent_request.py`

**Interfaces:**
- Produces: `RunAgentRequest(RunAgentInput)` com `.question -> str` (última mensagem `user`, sem espaços nas pontas) e `.conversation_id -> UUID` (`thread_id`). Falha de validação é `pydantic.ValidationError` (FastAPI → 422).

- [ ] **Step 1: Escrever os testes**

`tests/unit/app/api/requests/__init__.py` vazio. `tests/unit/app/api/requests/test_run_agent_request.py`:

```python
"""O body do POST /conversations/ask é o RunAgentInput do AG-UI (ADR-0019), com
três regras nossas por cima: threadId e runId são UUIDs, e a última mensagem é
do usuário e não está vazia. Tudo isso é 422 — nunca evento no stream."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.app.api.requests.run_agent_request import RunAgentRequest


def _body(**overrides) -> dict:
    body = {
        "threadId": str(uuid4()),
        "runId": str(uuid4()),
        "messages": [{"id": "m1", "role": "user", "content": "como funciona a renovação?"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    body.update(overrides)
    return body


def test_a_valid_body_exposes_question_and_conversation_id():
    body = _body()

    req = RunAgentRequest.model_validate(body)

    assert req.question == "como funciona a renovação?"
    assert req.conversation_id == UUID(body["threadId"])
    assert req.run_id == body["runId"]


def test_question_is_the_last_user_message_and_the_rest_is_ignored():
    req = RunAgentRequest.model_validate(_body(messages=[
        {"id": "m1", "role": "user", "content": "primeira"},
        {"id": "m2", "role": "assistant", "content": "resposta"},
        {"id": "m3", "role": "user", "content": "  segunda  "},
    ]))

    assert req.question == "segunda"


@pytest.mark.parametrize("field", ["threadId", "runId"])
def test_non_uuid_ids_are_rejected(field):
    with pytest.raises(ValidationError, match="UUID"):
        RunAgentRequest.model_validate(_body(**{field: "not-a-uuid"}))


def test_last_message_must_be_from_the_user():
    with pytest.raises(ValidationError, match="usuário"):
        RunAgentRequest.model_validate(_body(messages=[
            {"id": "m1", "role": "user", "content": "oi"},
            {"id": "m2", "role": "assistant", "content": "olá"},
        ]))


def test_empty_messages_are_rejected():
    with pytest.raises(ValidationError, match="messages"):
        RunAgentRequest.model_validate(_body(messages=[]))


def test_blank_question_is_rejected():
    with pytest.raises(ValidationError, match="vazia"):
        RunAgentRequest.model_validate(_body(messages=[{"id": "m1", "role": "user", "content": "   "}]))
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/unit/app/api/requests -q`
Expected: FAIL com `ModuleNotFoundError: src.app.api.requests.run_agent_request`.

- [ ] **Step 3: Implementar**

`src/app/api/requests/run_agent_request.py`:

```python
"""Body do POST /conversations/ask: o `RunAgentInput` do AG-UI (ADR-0019).

Regra 7 do CLAUDE.md: schema Pydantic mora em src/app/api/. O protocolo entra
aqui e no encoder de src/app/api/streaming/ — nunca em domain/ ou support/agent/.

O que é nosso por cima do protocolo:
- `threadId` é o id da conversa e `runId` é o run do LangSmith: ambos UUID.
- A pergunta é a ÚLTIMA mensagem, que precisa ser do usuário e ter texto. O
  resto do histórico do cliente é ignorado — a recência vem do Postgres.
- `tools`, `context`, `state`, `forwardedProps`, `resume`: aceitos e ignorados.
"""

from uuid import UUID

from ag_ui.core import RunAgentInput, UserMessage
from pydantic import model_validator


def _require_uuid(value: str, field: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} deve ser um UUID") from exc


def _text_of(message: UserMessage) -> str:
    content = message.content
    if not isinstance(content, str):
        raise ValueError("a última mensagem deve ser texto puro")
    return content.strip()


class RunAgentRequest(RunAgentInput):
    @model_validator(mode="after")
    def _oracle_rules(self):
        _require_uuid(self.thread_id, "threadId")
        _require_uuid(self.run_id, "runId")
        if not self.messages:
            raise ValueError("messages não pode ser vazio")
        last = self.messages[-1]
        if not isinstance(last, UserMessage) or last.role != "user":
            raise ValueError("a última mensagem deve ser do usuário (role=user)")
        if not _text_of(last):
            raise ValueError("a última mensagem não pode ser vazia")
        return self

    @property
    def question(self) -> str:
        return _text_of(self.messages[-1])

    @property
    def conversation_id(self) -> UUID:
        return UUID(self.thread_id)
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/unit/app/api/requests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/api/requests/run_agent_request.py tests/unit/app/api/requests
git commit -m "feat(api): RunAgentRequest — body AG-UI do /conversations/ask com as regras do oráculo

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: `ag_ui_encoder` — chunk → evento AG-UI

**Files:**
- Create: `src/app/api/streaming/__init__.py`, `src/app/api/streaming/ag_ui_encoder.py`, `tests/unit/app/api/streaming/__init__.py`, `tests/unit/app/api/streaming/test_ag_ui_encoder.py`

**Interfaces:**
- Produces (em `src/app/api/streaming/ag_ui_encoder.py`):
  - `SOURCES_EVENT = "oracle.sources"`, `STEP_EVENT = "oracle.step"`
  - `@dataclass RunContext(thread_id: str, run_id: str, message_id: str = uuid7(), text_started: bool = False)`
  - `run_started(ctx) -> BaseEvent`, `run_finished(ctx) -> BaseEvent`, `run_error(ctx, message: str) -> list[BaseEvent]` (fecha o texto aberto e emite `RUN_ERROR`)
  - `to_events(chunk: AgentStreamChunk, ctx: RunContext) -> list[BaseEvent]`
  - `encode(event: BaseEvent) -> str` e `CONTENT_TYPE = "text/event-stream"`
- Consumes: chunks da Task 2.

- [ ] **Step 1: Escrever os testes**

`tests/unit/app/api/streaming/__init__.py` vazio. `tests/unit/app/api/streaming/test_ag_ui_encoder.py`:

```python
"""Tradução chunk -> evento AG-UI (ADR-0019). Função pura, sem HTTP."""

import json

from ag_ui.core import EventType

from src.app.api.streaming.ag_ui_encoder import (
    SOURCES_EVENT,
    STEP_EVENT,
    RunContext,
    encode,
    run_error,
    run_finished,
    run_started,
    to_events,
)
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)


def _ctx() -> RunContext:
    return RunContext(thread_id="t1", run_id="r1")


def _types(events):
    return [e.type for e in events]


def test_run_started_and_finished_echo_thread_and_run():
    ctx = _ctx()
    started, finished = run_started(ctx), run_finished(ctx)
    assert (started.type, started.thread_id, started.run_id) == (EventType.RUN_STARTED, "t1", "r1")
    assert (finished.type, finished.thread_id, finished.run_id) == (EventType.RUN_FINISHED, "t1", "r1")


def test_text_message_start_is_emitted_once_before_the_first_delta():
    ctx = _ctx()
    first = to_events(TextChunk(text="olá "), ctx)
    second = to_events(TextChunk(text="mundo"), ctx)

    assert _types(first) == [EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_CONTENT]
    assert first[0].message_id == ctx.message_id and first[0].role == "assistant"
    assert first[1].delta == "olá "
    assert _types(second) == [EventType.TEXT_MESSAGE_CONTENT]
    assert second[0].message_id == ctx.message_id


def test_empty_text_produces_no_event():
    assert to_events(TextChunk(text=""), _ctx()) == []


def test_sources_close_the_text_message_and_carry_the_citation_payload():
    ctx = _ctx()
    to_events(TextChunk(text="x"), ctx)
    events = to_events(SourcesChunk(citations=[Citation("notion", "Doc", "https://n/a", "trecho")]), ctx)

    assert _types(events) == [EventType.TEXT_MESSAGE_END, EventType.CUSTOM]
    assert events[0].message_id == ctx.message_id
    assert events[1].name == SOURCES_EVENT
    assert events[1].value == {
        "citations": [{"source_type": "notion", "title": "Doc", "url": "https://n/a", "snippet": "trecho"}]
    }


def test_sources_without_any_text_do_not_emit_a_text_end():
    events = to_events(SourcesChunk(citations=[]), _ctx())
    assert _types(events) == [EventType.CUSTOM]
    assert events[0].value == {"citations": []}


def test_steps_map_to_step_events_and_detail_to_a_custom_event():
    ctx = _ctx()
    assert _types(to_events(StepChunk(name="gate", phase="started"), ctx)) == [EventType.STEP_STARTED]
    finished = to_events(StepChunk(name="retrieve", phase="finished", detail={"kept": 4}), ctx)
    assert _types(finished) == [EventType.STEP_FINISHED, EventType.CUSTOM]
    assert finished[0].step_name == "retrieve"
    assert finished[1].name == STEP_EVENT
    assert finished[1].value == {"step": "retrieve", "kept": 4}
    # sem detalhe, sem CUSTOM
    assert _types(to_events(StepChunk(name="answer", phase="finished"), ctx)) == [EventType.STEP_FINISHED]


def test_tool_calls_hang_off_the_assistant_message():
    ctx = _ctx()
    start = to_events(ToolCallStartChunk(id="c1", name="web_search"), ctx)
    args = to_events(ToolCallArgsChunk(id="c1", delta='{"query":"psp"}'), ctx)
    end = to_events(ToolCallEndChunk(id="c1"), ctx)
    result = to_events(ToolCallResultChunk(id="c1", status="error"), ctx)

    assert _types(start) == [EventType.TOOL_CALL_START]
    assert (start[0].tool_call_id, start[0].tool_call_name, start[0].parent_message_id) == ("c1", "web_search", ctx.message_id)
    assert _types(args) == [EventType.TOOL_CALL_ARGS] and args[0].delta == '{"query":"psp"}'
    assert _types(end) == [EventType.TOOL_CALL_END] and end[0].tool_call_id == "c1"
    assert _types(result) == [EventType.TOOL_CALL_RESULT]
    assert result[0].tool_call_id == "c1"
    assert json.loads(result[0].content) == {"status": "error"}
    assert result[0].message_id != ctx.message_id  # o result é uma mensagem "tool" própria


def test_run_error_closes_an_open_text_message_then_errors():
    ctx = _ctx()
    to_events(TextChunk(text="parcial"), ctx)
    events = run_error(ctx, "erro ao gerar a resposta")
    assert _types(events) == [EventType.TEXT_MESSAGE_END, EventType.RUN_ERROR]
    assert events[1].message == "erro ao gerar a resposta"

    # sem texto aberto, só o erro
    assert _types(run_error(_ctx(), "x")) == [EventType.RUN_ERROR]


def test_encode_is_sse_data_only_in_camel_case():
    line = encode(to_events(StepChunk(name="gate", phase="started"), _ctx())[0])
    assert line == 'data: {"type":"STEP_STARTED","stepName":"gate"}\n\n'
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `uv run pytest tests/unit/app/api/streaming -q`
Expected: FAIL com `ModuleNotFoundError: src.app.api.streaming`.

- [ ] **Step 3: Implementar**

`src/app/api/streaming/__init__.py` vazio.

`src/app/api/streaming/ag_ui_encoder.py`:

```python
"""Tradução dos chunks do port para eventos AG-UI (ADR-0019).

Camada `app`: aqui — e só aqui, além do request schema — o protocolo existe. O
grafo fala em dataclasses (`src/support/agent/ports.py`); esta função pura as
converte nos eventos que o `EventEncoder` serializa como `data: {json}`.

Invariantes do contrato (spec 2026-09-04, seção 1.2):
- um único `messageId` de assistente por run; `TEXT_MESSAGE_START` sai uma vez,
  antes do primeiro delta; `TEXT_MESSAGE_END` antes das fontes (ou do erro);
- `TOOL_CALL_RESULT.content` é só `{"status": ...}` — nunca conteúdo de tool.
"""

import json
from dataclasses import dataclass, field

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.encoder import EventEncoder
from uuid6 import uuid7

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    AgentStreamChunk,
    SourcesChunk,
    StepChunk,
    TextChunk,
    ToolCallArgsChunk,
    ToolCallEndChunk,
    ToolCallResultChunk,
    ToolCallStartChunk,
)

SOURCES_EVENT = "oracle.sources"
STEP_EVENT = "oracle.step"

_encoder = EventEncoder()
CONTENT_TYPE = _encoder.get_content_type()


@dataclass
class RunContext:
    """O que um run precisa lembrar entre chunks."""

    thread_id: str
    run_id: str
    message_id: str = field(default_factory=lambda: str(uuid7()))
    text_started: bool = False


def encode(event: BaseEvent) -> str:
    return _encoder.encode(event)


def run_started(ctx: RunContext) -> BaseEvent:
    return RunStartedEvent(type=EventType.RUN_STARTED, thread_id=ctx.thread_id, run_id=ctx.run_id)


def run_finished(ctx: RunContext) -> BaseEvent:
    return RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=ctx.thread_id, run_id=ctx.run_id)


def run_error(ctx: RunContext, message: str) -> list[BaseEvent]:
    """Falha no meio do stream: fecha o texto aberto e encerra com RUN_ERROR.
    Sem RUN_FINISHED depois — é o protocolo."""
    return [*_close_text(ctx), RunErrorEvent(type=EventType.RUN_ERROR, message=message)]


def _citation_payload(c: Citation) -> dict:
    return {"source_type": c.source_type, "title": c.title, "url": c.url, "snippet": c.snippet}


def _close_text(ctx: RunContext) -> list[BaseEvent]:
    if not ctx.text_started:
        return []
    ctx.text_started = False
    return [TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=ctx.message_id)]


def to_events(chunk: AgentStreamChunk, ctx: RunContext) -> list[BaseEvent]:
    match chunk:
        case TextChunk(text=text):
            if not text:
                return []
            out: list[BaseEvent] = []
            if not ctx.text_started:
                ctx.text_started = True
                out.append(
                    TextMessageStartEvent(
                        type=EventType.TEXT_MESSAGE_START, message_id=ctx.message_id, role="assistant"
                    )
                )
            out.append(
                TextMessageContentEvent(
                    type=EventType.TEXT_MESSAGE_CONTENT, message_id=ctx.message_id, delta=text
                )
            )
            return out
        case SourcesChunk(citations=citations):
            return [
                *_close_text(ctx),
                CustomEvent(
                    type=EventType.CUSTOM,
                    name=SOURCES_EVENT,
                    value={"citations": [_citation_payload(c) for c in citations]},
                ),
            ]
        case StepChunk(name=name, phase="started"):
            return [StepStartedEvent(type=EventType.STEP_STARTED, step_name=name)]
        case StepChunk(name=name, detail=detail):
            out = [StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name)]
            if detail is not None:
                out.append(CustomEvent(type=EventType.CUSTOM, name=STEP_EVENT, value={"step": name, **detail}))
            return out
        case ToolCallStartChunk(id=tc_id, name=name):
            return [
                ToolCallStartEvent(
                    type=EventType.TOOL_CALL_START,
                    tool_call_id=tc_id,
                    tool_call_name=name,
                    parent_message_id=ctx.message_id,
                )
            ]
        case ToolCallArgsChunk(id=tc_id, delta=delta):
            return [ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=tc_id, delta=delta)]
        case ToolCallEndChunk(id=tc_id):
            return [ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tc_id)]
        case ToolCallResultChunk(id=tc_id, status=status):
            return [
                ToolCallResultEvent(
                    type=EventType.TOOL_CALL_RESULT,
                    message_id=str(uuid7()),
                    tool_call_id=tc_id,
                    content=json.dumps({"status": status}),
                    role="tool",
                )
            ]
    return []
```

- [ ] **Step 4: Rodar os testes**

Run: `uv run pytest tests/unit/app/api/streaming tests/unit/support/agent/test_domain_boundary.py -q`
Expected: PASS (o teste de fronteira continua verde: `ag_ui` só em `src/app/`).

- [ ] **Step 5: Commit**

```bash
git add src/app/api/streaming tests/unit/app/api/streaming
git commit -m "feat(api): ag_ui_encoder — tradução pura chunk -> evento AG-UI

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Controller fala AG-UI + testes de integração + mapa de arquitetura

**Files:**
- Modify: `src/app/api/controllers/conversation_controller.py`
- Delete: `src/app/api/requests/ask_question_request.py`
- Modify: `tests/integration/api/test_ask_endpoint.py`, `tests/integration/api/test_ask_trace_persistence.py`
- Modify: `frontend/src/features/ops/architectureMap.ts` (caixa `ask`)

**Interfaces:**
- Consumes: `RunAgentRequest` (Task 6), encoder (Task 7), Action (Task 5), chunks (Task 2).
- Produces: `POST /conversations/ask` com o contrato da spec, seção 1.

- [ ] **Step 1: Reescrever os testes de integração do endpoint**

`tests/integration/api/test_ask_endpoint.py` completo:

```python
"""POST /conversations/ask fala AG-UI (ADR-0019): body RunAgentInput, resposta
`data: {json}` por evento. Usa o Postgres local, como o resto de integration/."""

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.fakes.auth import auth_headers
from tests.fakes.fake_turn_graph import FakeTurnGraph


@pytest_asyncio.fixture(autouse=True)
async def _dispose_db_engine_between_tests():
    yield
    from src.support.core.database import engine

    await engine.dispose()


class _FailingTurnGraph:
    """Emite um token e quebra no meio do stream — para o teste de erro."""

    async def start(self, question, history, deps=None, signals=None, knowledge=None, extra_config=None):
        if signals is not None:
            signals.outcome = "answer"

        async def _stream():
            from src.support.agent.ports import TextChunk

            yield TextChunk(text="ola ")
            raise RuntimeError("boom: engine caiu no meio do stream")

        return _stream()


def _run_input(question: str, thread_id: str | None = None, run_id: str | None = None) -> dict:
    return {
        "threadId": thread_id or str(uuid4()),
        "runId": run_id or str(uuid4()),
        "messages": [{"id": str(uuid4()), "role": "user", "content": question}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def _events(body: str) -> list[dict]:
    out = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def _text(events: list[dict]) -> str:
    return "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


def _sources(events: list[dict]) -> list[dict]:
    custom = [e for e in events if e["type"] == "CUSTOM" and e["name"] == "oracle.sources"]
    assert len(custom) == 1, f"esperava 1 oracle.sources, achei {len(custom)}"
    return custom[0]["value"]["citations"]


def _patch(monkeypatch, graph=None):
    import src.app.api.controllers.conversation_controller as ctrl
    from tests.fakes.fake_embeddings_client import FakeEmbeddingsClient

    monkeypatch.setattr(ctrl, "get_turn_graph_runner", lambda **kw: graph or FakeTurnGraph(answer="resposta de teste"))
    monkeypatch.setattr(ctrl, "get_embeddings_client", lambda: FakeEmbeddingsClient())


async def _roles(conversation_id: UUID, cleanup: bool = True) -> list[str]:
    from src.support.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                text("SELECT role FROM messages WHERE conversation_id = :cid ORDER BY created_at"),
                {"cid": conversation_id},
            )
        ).scalars().all()
        if cleanup:
            await s.execute(text("DELETE FROM conversations WHERE uuid = :cid"), {"cid": conversation_id})
            await s.commit()
    return list(rows)


@pytest.mark.asyncio
async def test_ask_streams_ag_ui_events_and_persists_both_turns(monkeypatch):
    _patch(monkeypatch)
    from main import app

    body = _run_input("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "event:" not in resp.text  # AG-UI: tudo em data:, sem campo event
        events = _events(resp.text)

    types = _types(events)
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert events[0]["threadId"] == body["threadId"]
    assert events[0]["runId"] == body["runId"]
    assert "STEP_STARTED" in types and "STEP_FINISHED" in types
    assert types.index("TEXT_MESSAGE_START") < types.index("TEXT_MESSAGE_CONTENT") < types.index("TEXT_MESSAGE_END")
    assert types.count("TEXT_MESSAGE_START") == 1
    assert _text(events) == "resposta de teste "
    assert [c["title"] for c in _sources(events)] == ["Doc"]
    message_ids = {e["messageId"] for e in events if e["type"].startswith("TEXT_MESSAGE")}
    assert len(message_ids) == 1

    assert await _roles(UUID(body["threadId"])) == ["user", "assistant"]


@pytest.mark.asyncio
async def test_ask_reuses_the_thread_id_as_the_conversation(monkeypatch):
    _patch(monkeypatch)
    from main import app

    thread_id = str(uuid4())
    headers = await auth_headers("asker@x.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/conversations/ask", json=_run_input("primeira", thread_id), headers=headers)
        second = await client.post("/conversations/ask", json=_run_input("segunda", thread_id), headers=headers)
        assert first.status_code == 200 and second.status_code == 200

    assert await _roles(UUID(thread_id)) == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_ask_with_someone_elses_thread_id_is_404(monkeypatch):
    _patch(monkeypatch)
    from main import app

    thread_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner = await client.post("/conversations/ask", json=_run_input("minha"), headers=await auth_headers("owner@x.com"))
        assert owner.status_code == 200
        conversation_id = _events(owner.text)[0]["threadId"]
        intruder = await client.post(
            "/conversations/ask",
            json=_run_input("dele", conversation_id),
            headers=await auth_headers("intruder@x.com"),
        )
        assert intruder.status_code == 404

    assert await _roles(UUID(conversation_id)) == ["user", "assistant"]  # nada do intruso


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(threadId="not-a-uuid"),
        lambda b: b.update(runId="123"),
        lambda b: b.update(messages=[{"id": "m", "role": "assistant", "content": "x"}]),
        lambda b: b.update(messages=[{"id": "m", "role": "user", "content": "   "}]),
        lambda b: b.update(messages=[]),
    ],
)
async def test_ask_with_an_invalid_body_is_422(monkeypatch, mutate):
    _patch(monkeypatch)
    from main import app

    body = _run_input("x")
    mutate(body)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ask_failure_emits_run_error_without_run_finished_and_does_not_persist_assistant(monkeypatch):
    _patch(monkeypatch, graph=_FailingTurnGraph())
    from main import app

    body = _run_input("o que é o onboarding?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        events = _events(resp.text)

    types = _types(events)
    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types
    assert events[-1]["message"] == "erro ao gerar a resposta"
    # o texto parcial que abriu foi fechado antes do erro
    assert types.index("TEXT_MESSAGE_END") < types.index("RUN_ERROR")

    assert await _roles(UUID(body["threadId"])) == ["user"]


@pytest.mark.asyncio
async def test_ask_streams_refusal_with_empty_sources_and_persists_both_turns(monkeypatch):
    _patch(
        monkeypatch,
        graph=FakeTurnGraph(
            answer="Não encontrei informações sobre isso na base de conhecimento.",
            outcome="refusal",
        ),
    )
    from main import app

    body = _run_input("qual a capital da Austrália?")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/conversations/ask", json=body, headers=await auth_headers("asker@x.com"))
        assert resp.status_code == 200
        events = _events(resp.text)

    assert _text(events) == "Não encontrei informações sobre isso na base de conhecimento. "
    assert _sources(events) == []
    assert _types(events)[-1] == "RUN_FINISHED"

    assert await _roles(UUID(body["threadId"])) == ["user", "assistant"]
```

- [ ] **Step 2: Adaptar o teste de persistência do trace**

Em `tests/integration/api/test_ask_trace_persistence.py`:

Substituir `_parse_conversation_id` e `_concat_tokens` por:

```python
def _run_input(question: str, thread_id: str | None = None, run_id: str | None = None) -> dict:
    from uuid import uuid4

    return {
        "threadId": thread_id or str(uuid4()),
        "runId": run_id or str(uuid4()),
        "messages": [{"id": str(uuid4()), "role": "user", "content": question}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def _events(body: str) -> list[dict]:
    import json

    out = []
    for block in body.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def _text(events: list[dict]) -> str:
    return "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
```

Em `test_trace_row_exists_after_a_successful_ask`: montar `body = _run_input("o que é o PSP?")`, enviar `json=body`, trocar `assert "event: done" in body` por `assert _events(resp.text)[-1]["type"] == "RUN_FINISHED"`, chamar `_fetch_trace(UUID(body["threadId"]))`, e trocar a última asserção por:

```python
    # ADR-0019: o runId do cliente É o run do LangSmith — um turno da tela liga
    # ao trace sem intermediário.
    assert trace["langsmith_run_id"] == body["runId"]
```

Em `test_failed_turn_is_traced_even_though_the_answer_is_not_persisted`: `body = _run_input("vai falhar")`, `json=body`, `assert _events(resp.text)[-1]["type"] == "RUN_ERROR"`, `conversation_id = UUID(body["threadId"])`.

Em `test_refusal_leaves_engine_ms_and_first_token_ms_null`: `body = _run_input("qual a capital da Austrália?")`, `json=body`, `assert "Não encontrei informações sobre isso na base de conhecimento." in _text(_events(resp.text))`, `_fetch_trace(UUID(body["threadId"]))`.

- [ ] **Step 3: Rodar para ver falhar**

Run: `uv run pytest tests/integration/api/test_ask_endpoint.py tests/integration/api/test_ask_trace_persistence.py -q`
Expected: FAIL — 422 no body atual (`question` obrigatório) ou eventos `event: token` no corpo.

- [ ] **Step 4: Reescrever o controller**

`src/app/api/controllers/conversation_controller.py` — imports e `ask`:

```python
import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi.responses import StreamingResponse

from src.app.api.requests.run_agent_request import RunAgentRequest
from src.app.api.responses.conversation_responses import (
    ConversationDetailResponse,
    ConversationSummaryResponse,
)
from src.app.api.streaming.ag_ui_encoder import (
    CONTENT_TYPE,
    RunContext,
    encode,
    run_error,
    run_finished,
    run_started,
    to_events,
)
from src.domain.conversations.actions.answer_question_action import AnswerQuestionAction
from src.domain.conversations.actions.append_assistant_message_action import (
    AppendAssistantMessageAction,
)
from src.domain.conversations.actions.get_conversation_action import GetConversationAction
from src.domain.conversations.actions.list_conversations_action import ListConversationsAction
from src.domain.documents.actions.search_knowledge_base_action import SearchKnowledgeBaseAction
from src.domain.observability.actions.record_turn_trace_action import RecordTurnTraceAction
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.graph import get_turn_graph_runner
from src.support.agent.ports import SourcesChunk, TextChunk
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.context import CurrentAsyncSessionContext, CurrentRequestContext
from src.support.core.session_scope import run_in_async_session
from src.support.observability.langsmith import hash_email

logger = logging.getLogger(__name__)


class ConversationController:
    @staticmethod
    async def ask(data: RunAgentRequest) -> StreamingResponse:
        """POST /conversations/ask — AG-UI (ADR-0019).

        Body é o `RunAgentInput`; resposta é a sequência de eventos do protocolo
        em `data: {json}`. `threadId` é a conversa, `runId` é o run do LangSmith.
        """
        user_email = CurrentRequestContext.get_user().email
        search = SearchKnowledgeBaseAction(embeddings=get_embeddings_client())
        run_id = data.run_id
        action = AnswerQuestionAction(
            graph=get_turn_graph_runner(run_id=run_id, user_hash=hash_email(user_email)),
            search=search,
        )

        # Conversa + user message são gravadas aqui (sessão do request viva).
        conversation_id, stream, draft = await action.execute(
            data.question, data.conversation_id, user_email
        )
        # Gravado sempre — coluna barata; o link só aparece na UI quando
        # LANGSMITH_PROJECT_URL está configurado (ver run_url).
        draft.langsmith_run_id = run_id

        ctx = RunContext(thread_id=str(conversation_id), run_id=run_id)
        captured: dict = {"text": "", "citations": []}

        async def event_source() -> AsyncIterator[str]:
            yield encode(run_started(ctx))
            failed = False
            try:
                async for chunk in stream:
                    if isinstance(chunk, TextChunk):
                        captured["text"] += chunk.text
                    elif isinstance(chunk, SourcesChunk):
                        captured["citations"] = chunk.citations
                    for event in to_events(chunk, ctx):
                        yield encode(event)
            except Exception as exc:
                failed = True
                logger.exception("stream falhou durante /conversations/ask")
                draft.outcome = "error"
                # A mensagem ao usuário (RUN_ERROR) continua genérica; só o
                # trace fica informativo. Truncado em 512: é o tamanho da coluna.
                draft.error = f"{type(exc).__name__}: {exc}"[:512]
                for event in run_error(ctx, "erro ao gerar a resposta"):
                    yield encode(event)

            draft.citations_count = len(captured["citations"])
            _absorb_engine_metrics(draft)

            # A resposta só é persistida em sucesso (decisão do M2); o trace é
            # gravado SEMPRE — turno que quebrou é o que mais interessa no trace.
            try:
                await _persist_turn(
                    conversation_id,
                    draft,
                    captured["text"] if (not failed and captured["text"]) else None,
                    captured["citations"],
                )
            except Exception:
                logger.exception("falha ao persistir turno (resposta e/ou trace)")

            # RUN_FINISHED só depois de persistir: quando o cliente o recebe, a
            # conversa já está gravada e a sidebar pode recarregar. Depois de
            # RUN_ERROR não há RUN_FINISHED — é o protocolo.
            if not failed:
                yield encode(run_finished(ctx))

        return StreamingResponse(event_source(), media_type=CONTENT_TYPE)
```

Manter `list`, `get`, `_engine_ran`, `_absorb_engine_metrics` e `_persist_turn` como estão. Remover `import json`, `_sse`, `_citation_payload`, o import de `uuid7` (cola da Task 5) e o de `new_run_id`.

Apagar `src/app/api/requests/ask_question_request.py`.

- [ ] **Step 5: Atualizar o mapa de arquitetura no mesmo commit**

Em `frontend/src/features/ops/architectureMap.ts`, substituir a caixa `ask`:

```ts
      {
        id: "ask",
        label: "Pergunta (AG-UI)",
        description: "POST /conversations/ask recebe RunAgentInput e responde eventos AG-UI: passos do grafo, tool calls, texto e fontes. Tradução chunk → evento na camada app.",
        files: [
          "src/app/api/controllers/conversation_controller.py",
          "src/app/api/requests/run_agent_request.py",
          "src/app/api/streaming/ag_ui_encoder.py",
        ],
      },
```

- [ ] **Step 6: Rodar backend inteiro e o teste do mapa**

Run: `uv run pytest -q`
Expected: PASS.

Run: `cd frontend && npx vitest run src/features/ops/architectureMap.test.ts`
Expected: PASS (os três arquivos existem).

Run: `uv run python -c "from main import app; print('OK')"`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add src/app/api/controllers/conversation_controller.py src/app/api/requests/ask_question_request.py tests/integration/api frontend/src/features/ops/architectureMap.ts
git commit -m "feat(api): POST /conversations/ask fala AG-UI — RunAgentInput na entrada, eventos do protocolo na saída

threadId = conversa (find-or-create; alheia é 404), runId = run do LangSmith.
RUN_ERROR encerra sem RUN_FINISHED; persistência pós-stream inalterada.
Mapa de arquitetura atualizado no mesmo commit (ADR-0019).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Frontend — parser AG-UI e tradução para `AskEvent`

**Files:**
- Modify: `frontend/src/lib/api/sse.ts`, `frontend/src/lib/types.ts:34-39`, `frontend/src/lib/api/conversations.ts:34-56`, `frontend/src/lib/demo/demoStream.ts`
- Create: `frontend/src/lib/api/agui.ts`, `frontend/src/lib/api/agui.test.ts`

**Interfaces:**
- Produces (`lib/types.ts`):
  ```ts
  export type AskEvent =
    | { type: "run_started"; conversationId: string }
    | { type: "step"; name: string; phase: "started" | "finished"; detail?: Record<string, unknown> }
    | { type: "tool_call_start"; id: string; name: string }
    | { type: "tool_call_args"; id: string; delta: string }
    | { type: "tool_call_end"; id: string }
    | { type: "tool_call_result"; id: string; status: "ok" | "error" }
    | { type: "token"; text: string }
    | { type: "sources"; citations: Citation[] }
    | { type: "error"; message: string }
    | { type: "done" };
  ```
- Produces (`lib/api/agui.ts`): `AgUiEvent`, `parseAgUiEvent(data: string): AgUiEvent | null`, `parseAgUiStream(body): AsyncGenerator<AgUiEvent>`, `buildRunAgentInput(question, threadId?)`, `toAskEvents(events: AsyncIterable<AgUiEvent>): AsyncGenerator<AskEvent>`, `SOURCES_EVENT`, `STEP_EVENT`.
- Produces (`lib/api/sse.ts`): `parseSSEData(stream): AsyncGenerator<string>` (substitui `parseSSE`).

- [ ] **Step 1: Escrever os testes**

`frontend/src/lib/api/agui.test.ts`:

```ts
// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { AskEvent } from "../types";
import { buildRunAgentInput, parseAgUiEvent, toAskEvents, type AgUiEvent } from "./agui";

async function* from(events: AgUiEvent[]): AsyncGenerator<AgUiEvent> {
  for (const e of events) yield e;
}

async function collect(events: AgUiEvent[]): Promise<AskEvent[]> {
  const out: AskEvent[] = [];
  for await (const e of toAskEvents(from(events))) out.push(e);
  return out;
}

describe("parseAgUiEvent", () => {
  it("parses a camelCase AG-UI event", () => {
    expect(parseAgUiEvent('{"type":"STEP_STARTED","stepName":"gate"}')).toEqual({ type: "STEP_STARTED", stepName: "gate" });
  });

  it("drops malformed JSON and unknown types", () => {
    expect(parseAgUiEvent("{not json")).toBeNull();
    expect(parseAgUiEvent('{"type":"SOMETHING_NEW","x":1}')).toBeNull();
    expect(parseAgUiEvent('"a string"')).toBeNull();
  });
});

describe("buildRunAgentInput", () => {
  it("uses the given threadId or mints one, always with a fresh runId and empty protocol fields", () => {
    const withThread = buildRunAgentInput("oi", "thread-1");
    expect(withThread.threadId).toBe("thread-1");
    expect(withThread.runId).toMatch(/[0-9a-f-]{36}/);
    expect(withThread.messages).toEqual([{ id: expect.any(String), role: "user", content: "oi" }]);
    expect(withThread.tools).toEqual([]);
    expect(withThread.context).toEqual([]);
    expect(withThread.forwardedProps).toEqual({});

    const fresh = buildRunAgentInput("oi");
    expect(fresh.threadId).toMatch(/[0-9a-f-]{36}/);
    expect(fresh.runId).not.toBe(fresh.threadId);
  });
});

describe("toAskEvents", () => {
  it("translates the happy path in order", async () => {
    const out = await collect([
      { type: "RUN_STARTED", threadId: "t1", runId: "r1" },
      { type: "STEP_STARTED", stepName: "gate" },
      { type: "STEP_FINISHED", stepName: "gate" },
      { type: "CUSTOM", name: "oracle.step", value: { step: "gate", retrieve: true, degraded: false } },
      { type: "TEXT_MESSAGE_START", messageId: "m1", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "olá" },
      { type: "TEXT_MESSAGE_END", messageId: "m1" },
      { type: "CUSTOM", name: "oracle.sources", value: { citations: [{ source_type: "notion", title: "T", url: "u", snippet: "s" }] } },
      { type: "RUN_FINISHED", threadId: "t1", runId: "r1" },
    ]);

    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } },
      { type: "token", text: "olá" },
      { type: "sources", citations: [{ source_type: "notion", title: "T", url: "u", snippet: "s" }] },
      { type: "done" },
    ]);
  });

  it("a STEP_FINISHED without a following oracle.step is released on the next event", async () => {
    const out = await collect([
      { type: "STEP_FINISHED", stepName: "answer" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "x" },
    ]);
    expect(out).toEqual([
      { type: "step", name: "answer", phase: "finished" },
      { type: "token", text: "x" },
    ]);
  });

  it("a trailing STEP_FINISHED is flushed when the stream ends", async () => {
    expect(await collect([{ type: "STEP_FINISHED", stepName: "answer" }])).toEqual([
      { type: "step", name: "answer", phase: "finished" },
    ]);
  });

  it("an oracle.step for a different step does not fuse", async () => {
    const out = await collect([
      { type: "STEP_FINISHED", stepName: "gate" },
      { type: "CUSTOM", name: "oracle.step", value: { step: "retrieve", kept: 2 } },
    ]);
    expect(out).toEqual([{ type: "step", name: "gate", phase: "finished" }]);
  });

  it("translates tool calls and reads the status out of TOOL_CALL_RESULT.content", async () => {
    const out = await collect([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "web_search", parentMessageId: "m1" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '{"query":' },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: '"psp"}' },
      { type: "TOOL_CALL_END", toolCallId: "c1" },
      { type: "TOOL_CALL_RESULT", messageId: "mt", toolCallId: "c1", content: '{"status":"error"}', role: "tool" },
    ]);
    expect(out).toEqual([
      { type: "tool_call_start", id: "c1", name: "web_search" },
      { type: "tool_call_args", id: "c1", delta: '{"query":' },
      { type: "tool_call_args", id: "c1", delta: '"psp"}' },
      { type: "tool_call_end", id: "c1" },
      { type: "tool_call_result", id: "c1", status: "error" },
    ]);
  });

  it("RUN_ERROR becomes error and is terminal (no done)", async () => {
    const out = await collect([
      { type: "RUN_STARTED", threadId: "t1", runId: "r1" },
      { type: "RUN_ERROR", message: "erro ao gerar a resposta" },
    ]);
    expect(out).toEqual([
      { type: "run_started", conversationId: "t1" },
      { type: "error", message: "erro ao gerar a resposta" },
    ]);
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/lib/api/agui.test.ts`
Expected: FAIL — módulo `./agui` não existe.

- [ ] **Step 3: Implementar `sse.ts`, `types.ts`, `agui.ts`**

`frontend/src/lib/api/sse.ts` (conteúdo completo):

```ts
/** Lê um stream SSE e devolve o payload `data:` de cada bloco.
 *
 * O AG-UI põe tudo no JSON (ADR-0019): `event:`, `id:` e `retry:` são
 * ignorados, como o protocolo pede. Linhas `data:` múltiplas no mesmo bloco
 * são unidas com "\n". */
export async function* parseSSEData(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const data = readData(part);
      if (data !== null) yield data;
    }
  }
  const tail = readData(buffer);
  if (tail !== null) yield tail;
}

function readData(block: string): string | null {
  const lines = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());
  return lines.length ? lines.join("\n") : null;
}
```

`frontend/src/lib/types.ts` — substituir o bloco `AskEvent`:

```ts
/** Eventos internos do turno. É o que o hook consome; a tradução do protocolo
 * AG-UI para isto fica em lib/api/agui.ts (ADR-0019). */
export type AskEvent =
  | { type: "run_started"; conversationId: string }
  | { type: "step"; name: string; phase: "started" | "finished"; detail?: Record<string, unknown> }
  | { type: "tool_call_start"; id: string; name: string }
  | { type: "tool_call_args"; id: string; delta: string }
  | { type: "tool_call_end"; id: string }
  | { type: "tool_call_result"; id: string; status: "ok" | "error" }
  | { type: "token"; text: string }
  | { type: "sources"; citations: Citation[] }
  | { type: "error"; message: string }
  | { type: "done" };
```

`frontend/src/lib/api/agui.ts`:

```ts
/** AG-UI no fio (ADR-0019): tipos dos eventos que consumimos, parser tolerante
 * e a tradução para o `AskEvent` interno. O hook e a UI não conhecem o
 * protocolo — só este módulo. */
import type { AskEvent, Citation } from "../types";
import { parseSSEData } from "./sse";

export type AgUiEvent =
  | { type: "RUN_STARTED"; threadId: string; runId: string }
  | { type: "RUN_FINISHED"; threadId: string; runId: string }
  | { type: "RUN_ERROR"; message: string; code?: string }
  | { type: "STEP_STARTED"; stepName: string }
  | { type: "STEP_FINISHED"; stepName: string }
  | { type: "TEXT_MESSAGE_START"; messageId: string; role: "assistant" }
  | { type: "TEXT_MESSAGE_CONTENT"; messageId: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; messageId: string }
  | { type: "TOOL_CALL_START"; toolCallId: string; toolCallName: string; parentMessageId?: string }
  | { type: "TOOL_CALL_ARGS"; toolCallId: string; delta: string }
  | { type: "TOOL_CALL_END"; toolCallId: string }
  | { type: "TOOL_CALL_RESULT"; messageId: string; toolCallId: string; content: string; role?: "tool" }
  | { type: "CUSTOM"; name: string; value: unknown };

const KNOWN_TYPES = new Set<string>([
  "RUN_STARTED", "RUN_FINISHED", "RUN_ERROR",
  "STEP_STARTED", "STEP_FINISHED",
  "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
  "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
  "CUSTOM",
]);

export const SOURCES_EVENT = "oracle.sources";
export const STEP_EVENT = "oracle.step";

/** JSON inválido ou tipo desconhecido → null (tolerância a eventos futuros). */
export function parseAgUiEvent(data: string): AgUiEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const type = (parsed as { type?: unknown }).type;
  if (typeof type !== "string" || !KNOWN_TYPES.has(type)) return null;
  return parsed as AgUiEvent;
}

export async function* parseAgUiStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<AgUiEvent> {
  for await (const data of parseSSEData(stream)) {
    const event = parseAgUiEvent(data);
    if (event) yield event;
  }
}

export interface RunAgentInput {
  threadId: string;
  runId: string;
  messages: Array<{ id: string; role: "user"; content: string }>;
  tools: never[];
  context: never[];
  forwardedProps: Record<string, never>;
}

/** threadId = conversa (o cliente gera; o servidor faz find-or-create).
 * runId = run do LangSmith. O protocolo exige tools/context/forwardedProps. */
export function buildRunAgentInput(question: string, threadId?: string): RunAgentInput {
  return {
    threadId: threadId ?? crypto.randomUUID(),
    runId: crypto.randomUUID(),
    messages: [{ id: crypto.randomUUID(), role: "user", content: question }],
    tools: [],
    context: [],
    forwardedProps: {},
  };
}

function isStepDetail(value: unknown, step: string): value is Record<string, unknown> {
  return !!value && typeof value === "object" && (value as { step?: unknown }).step === step;
}

function detailOf(value: Record<string, unknown>): Record<string, unknown> {
  const detail: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value)) if (key !== "step") detail[key] = v;
  return detail;
}

function resultStatus(content: string): "ok" | "error" {
  try {
    const parsed = JSON.parse(content) as { status?: unknown };
    return parsed?.status === "error" ? "error" : "ok";
  } catch {
    return "ok";
  }
}

function readCitations(value: unknown): Citation[] {
  const list = (value as { citations?: unknown } | null)?.citations;
  return Array.isArray(list) ? (list as Citation[]) : [];
}

/** STEP_FINISHED pode vir seguido de um CUSTOM oracle.step com o detalhe: os
 * dois viram um único `step finished`. O finished fica pendente até o próximo
 * evento (ou o fim do stream). */
export async function* toAskEvents(events: AsyncIterable<AgUiEvent>): AsyncGenerator<AskEvent> {
  let pending: string | null = null;
  for await (const ev of events) {
    if (pending !== null) {
      if (ev.type === "CUSTOM" && ev.name === STEP_EVENT && isStepDetail(ev.value, pending)) {
        yield { type: "step", name: pending, phase: "finished", detail: detailOf(ev.value) };
        pending = null;
        continue;
      }
      yield { type: "step", name: pending, phase: "finished" };
      pending = null;
    }
    switch (ev.type) {
      case "RUN_STARTED":
        yield { type: "run_started", conversationId: ev.threadId };
        break;
      case "STEP_STARTED":
        yield { type: "step", name: ev.stepName, phase: "started" };
        break;
      case "STEP_FINISHED":
        pending = ev.stepName;
        break;
      case "TEXT_MESSAGE_CONTENT":
        if (ev.delta) yield { type: "token", text: ev.delta };
        break;
      case "TOOL_CALL_START":
        yield { type: "tool_call_start", id: ev.toolCallId, name: ev.toolCallName };
        break;
      case "TOOL_CALL_ARGS":
        yield { type: "tool_call_args", id: ev.toolCallId, delta: ev.delta };
        break;
      case "TOOL_CALL_END":
        yield { type: "tool_call_end", id: ev.toolCallId };
        break;
      case "TOOL_CALL_RESULT":
        yield { type: "tool_call_result", id: ev.toolCallId, status: resultStatus(ev.content) };
        break;
      case "CUSTOM":
        if (ev.name === SOURCES_EVENT) yield { type: "sources", citations: readCitations(ev.value) };
        break;
      case "RUN_ERROR":
        yield { type: "error", message: ev.message || "erro" };
        break;
      case "RUN_FINISHED":
        yield { type: "done" };
        break;
      default:
        // TEXT_MESSAGE_START/END: o texto já chega pelos deltas.
        break;
    }
  }
  if (pending !== null) yield { type: "step", name: pending, phase: "finished" };
}
```

- [ ] **Step 4: Ligar `askStream` e o demo**

`frontend/src/lib/api/conversations.ts` — trocar o import de `parseSSE` por `import { buildRunAgentInput, parseAgUiStream, toAskEvents } from "./agui";` e substituir `askStream` e `safeParse`:

```ts
export async function* askStream(input: AskInput): AsyncGenerator<AskEvent> {
  const resp = await fetch(apiUrl("/conversations/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(buildRunAgentInput(input.question, input.conversationId)),
  });
  if (resp.status === 401) {
    handleUnauthorized();
    yield { type: "error", message: "Sessão expirada — faça login de novo." };
    return;
  }
  if (!resp.ok || !resp.body) {
    yield { type: "error", message: `Falha na requisição (${resp.status})` };
    return;
  }
  yield* toAskEvents(parseAgUiStream(resp.body));
}
```

(Remover `safeParse`.)

`frontend/src/lib/demo/demoStream.ts` (conteúdo completo):

```ts
import type { AskEvent, AskInput } from "../types";
import { DEMO_ANSWER, DEMO_ANSWER_CITATIONS } from "./demoData";

const ERROR_SENTINEL = "[demo-error]";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function* demoStream(input: AskInput): AsyncGenerator<AskEvent> {
  const conversationId = input.conversationId ?? "demo-new";
  yield { type: "run_started", conversationId };

  if (input.question.includes(ERROR_SENTINEL)) {
    await delay(400);
    yield { type: "error", message: "Não consegui gerar a resposta agora. Tente novamente." };
    return;
  }

  yield { type: "step", name: "gate", phase: "started" };
  await delay(300);
  yield { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } };
  yield { type: "step", name: "retrieve", phase: "started" };
  await delay(300);
  yield { type: "step", name: "retrieve", phase: "finished", detail: { kept: DEMO_ANSWER_CITATIONS.length } };
  yield { type: "step", name: "answer", phase: "started" };
  await delay(200);
  for (const word of DEMO_ANSWER.split(" ")) {
    yield { type: "token", text: word + " " };
    await delay(40);
  }
  yield { type: "step", name: "answer", phase: "finished" };
  yield { type: "sources", citations: DEMO_ANSWER_CITATIONS };
  yield { type: "done" };
}
```

- [ ] **Step 5: Rodar os testes e o typecheck**

Run: `cd frontend && npx vitest run src/lib/api/agui.test.ts && npx tsc --noEmit`
Expected: testes PASS; `tsc` acusa só `useAskStream.ts` (ainda usa `evt.type === "conversation"`) — resolvido na Task 10. Se acusar outro arquivo, corrija aqui.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api/sse.ts frontend/src/lib/api/agui.ts frontend/src/lib/api/agui.test.ts frontend/src/lib/api/conversations.ts frontend/src/lib/types.ts frontend/src/lib/demo/demoStream.ts
git commit -m "feat(frontend): parser AG-UI e tradução para AskEvent; askStream envia RunAgentInput

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: `useAskStream` ganha `activity` e trata stream cortado

**Files:**
- Modify: `frontend/src/hooks/useAskStream.ts`, `frontend/src/hooks/useAskStream.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type StepItem = { kind: "step"; name: string; status: "running" | "done"; detail?: Record<string, unknown> };
  export type ToolItem = { kind: "tool"; id: string; name: string; argsRaw: string; args?: Record<string, unknown>; status: "pending" | "running" | "ok" | "error" };
  export type ActivityItem = StepItem | ToolItem;
  export function applyActivity(prev: ActivityItem[], evt: AskEvent): ActivityItem[];
  ```
  e o hook devolve também `activity: ActivityItem[]`.

- [ ] **Step 1: Atualizar e ampliar os testes**

Em `frontend/src/hooks/useAskStream.test.ts`:

- No mock `askStream`, trocar `{ type: "conversation", id: "stale-convo" }` por `{ type: "run_started", conversationId: "stale-convo" }`.
- Nos cenários, trocar `{ type: "conversation", id: "c9" }` por `{ type: "run_started", conversationId: "c9" }` e `{ type: "conversation", id: "c-second" }` por `{ type: "run_started", conversationId: "c-second" }`.
- No teste de erro, remover o `{ type: "done" }` após o erro (o protocolo não manda `done` depois de `RUN_ERROR`).

Acrescentar, dentro do `describe("useAskStream")`:

```ts
  it("builds the activity timeline in arrival order, with steps and tool calls interleaved", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } },
      { type: "step", name: "retrieve", phase: "started" },
      { type: "step", name: "retrieve", phase: "finished", detail: { kept: 4 } },
      { type: "step", name: "answer", phase: "started" },
      { type: "tool_call_start", id: "t1", name: "web_search" },
      { type: "tool_call_args", id: "t1", delta: '{"query":' },
      { type: "tool_call_args", id: "t1", delta: '"psp"}' },
      { type: "tool_call_end", id: "t1" },
      { type: "tool_call_result", id: "t1", status: "ok" },
      { type: "token", text: "resposta" },
      { type: "step", name: "answer", phase: "finished" },
      { type: "sources", citations: [] },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    await waitFor(() => expect(result.current.status).toBe("done"));

    expect(result.current.activity).toEqual([
      { kind: "step", name: "gate", status: "done", detail: { retrieve: true, degraded: false } },
      { kind: "step", name: "retrieve", status: "done", detail: { kept: 4 } },
      { kind: "step", name: "answer", status: "done", detail: undefined },
      { kind: "tool", id: "t1", name: "web_search", argsRaw: '{"query":"psp"}', args: { query: "psp" }, status: "ok" },
    ]);
  });

  it("a stream that ends without done or error is reported as a broken connection", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "token", text: "parcial" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.errorMessage).toBe("conexão interrompida");
  });

  it("reset() clears the activity", async () => {
    scenario.events = [
      { type: "run_started", conversationId: "c1" },
      { type: "step", name: "gate", phase: "started" },
      { type: "done" },
    ];
    const { result } = renderHook(() => useAskStream());
    await act(async () => {
      await result.current.ask({ question: "oi" });
    });
    expect(result.current.activity).toHaveLength(1);
    act(() => result.current.reset());
    expect(result.current.activity).toEqual([]);
  });
```

E um `describe` novo para o redutor puro:

```ts
import { applyActivity, type ActivityItem } from "./useAskStream";

describe("applyActivity", () => {
  it("a finished step without a prior started enters already done", () => {
    expect(applyActivity([], { type: "step", name: "gate", phase: "finished", detail: { retrieve: false } })).toEqual([
      { kind: "step", name: "gate", status: "done", detail: { retrieve: false } },
    ]);
  });

  it("tool call lifecycle: pending → running (args parsed) → ok/error", () => {
    let items: ActivityItem[] = applyActivity([], { type: "tool_call_start", id: "t1", name: "fetch_notion_page" });
    expect(items).toEqual([{ kind: "tool", id: "t1", name: "fetch_notion_page", argsRaw: "", status: "pending" }]);
    items = applyActivity(items, { type: "tool_call_args", id: "t1", delta: '{"page_id":"abc"}' });
    items = applyActivity(items, { type: "tool_call_end", id: "t1" });
    expect(items[0]).toMatchObject({ status: "running", args: { page_id: "abc" } });
    items = applyActivity(items, { type: "tool_call_result", id: "t1", status: "error" });
    expect(items[0]).toMatchObject({ status: "error" });
  });

  it("events for unknown tool ids and non-activity events leave the list untouched", () => {
    const items: ActivityItem[] = [{ kind: "step", name: "gate", status: "running" }];
    expect(applyActivity(items, { type: "tool_call_args", id: "ghost", delta: "x" })).toBe(items);
    expect(applyActivity(items, { type: "token", text: "x" })).toBe(items);
  });

  it("unparseable args stay undefined but the tool still runs", () => {
    let items: ActivityItem[] = applyActivity([], { type: "tool_call_start", id: "t1", name: "web_search" });
    items = applyActivity(items, { type: "tool_call_args", id: "t1", delta: "{oops" });
    items = applyActivity(items, { type: "tool_call_end", id: "t1" });
    expect(items[0]).toMatchObject({ status: "running", args: undefined, argsRaw: "{oops" });
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/hooks/useAskStream.test.ts`
Expected: FAIL — `applyActivity` não exportado; `activity` undefined.

- [ ] **Step 3: Implementar o hook**

`frontend/src/hooks/useAskStream.ts` (conteúdo completo):

```ts
import { useCallback, useRef, useState } from "react";
import type { AskEvent, AskInput, Citation } from "../lib/types";
import { askStream } from "../data/source";

export type AskStatus = "idle" | "thinking" | "streaming" | "done" | "error";

export type StepItem = {
  kind: "step";
  name: string;
  status: "running" | "done";
  detail?: Record<string, unknown>;
};

export type ToolItem = {
  kind: "tool";
  id: string;
  name: string;
  /** JSON dos argumentos como chega, em fragmentos. */
  argsRaw: string;
  /** Parseado no `tool_call_end`; undefined se o JSON não fechar. */
  args?: Record<string, unknown>;
  status: "pending" | "running" | "ok" | "error";
};

/** Linha do tempo do turno em ordem de chegada — passos e tool calls
 * intercalados ("Respondendo" → "Buscando na web" → "Respondendo" continua). */
export type ActivityItem = StepItem | ToolItem;

function parseArgs(raw: string): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

function updateTool(prev: ActivityItem[], id: string, patch: (t: ToolItem) => ToolItem): ActivityItem[] {
  const idx = prev.findIndex((i) => i.kind === "tool" && i.id === id);
  if (idx === -1) return prev;
  const next = [...prev];
  next[idx] = patch(next[idx] as ToolItem);
  return next;
}

/** Redutor puro: um AskEvent → nova lista. Devolve a MESMA referência quando o
 * evento não é de atividade ou não encontra o item, para não re-renderizar à toa. */
export function applyActivity(prev: ActivityItem[], evt: AskEvent): ActivityItem[] {
  switch (evt.type) {
    case "step": {
      if (evt.phase === "started") {
        return [...prev, { kind: "step", name: evt.name, status: "running" }];
      }
      let idx = -1;
      for (let i = prev.length - 1; i >= 0; i--) {
        const item = prev[i];
        if (item.kind === "step" && item.name === evt.name && item.status === "running") {
          idx = i;
          break;
        }
      }
      if (idx === -1) {
        return [...prev, { kind: "step", name: evt.name, status: "done", detail: evt.detail }];
      }
      const next = [...prev];
      next[idx] = { ...(next[idx] as StepItem), status: "done", detail: evt.detail };
      return next;
    }
    case "tool_call_start":
      return [...prev, { kind: "tool", id: evt.id, name: evt.name, argsRaw: "", status: "pending" }];
    case "tool_call_args":
      return updateTool(prev, evt.id, (t) => ({ ...t, argsRaw: t.argsRaw + evt.delta }));
    case "tool_call_end":
      return updateTool(prev, evt.id, (t) => ({ ...t, args: parseArgs(t.argsRaw), status: "running" }));
    case "tool_call_result":
      return updateTool(prev, evt.id, (t) => ({ ...t, status: evt.status }));
    default:
      return prev;
  }
}

export function useAskStream() {
  const [status, setStatus] = useState<AskStatus>("idle");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Generation guard: bumped on every ask()/reset() so a superseded run's
  // events (from a prior in-flight async-generator loop) can be told apart
  // from the current one and dropped instead of corrupting shared state.
  const genRef = useRef(0);

  const reset = useCallback(() => {
    genRef.current++;
    setStatus("idle");
    setAnswer("");
    setCitations([]);
    setActivity([]);
    setErrorMessage(null);
  }, []);

  const ask = useCallback(async (input: AskInput) => {
    const myGen = ++genRef.current;
    setStatus("thinking");
    setAnswer("");
    setCitations([]);
    setActivity([]);
    setErrorMessage(null);
    // O protocolo termina em RUN_FINISHED ou RUN_ERROR. Se o stream acabar sem
    // nenhum dos dois (queda de conexão, proxy), é erro — não um "streaming"
    // preso para sempre.
    let terminated = false;
    try {
      for await (const evt of askStream(input)) {
        if (genRef.current !== myGen) return;
        switch (evt.type) {
          case "run_started":
            setConversationId(evt.conversationId);
            break;
          case "token":
            setStatus("streaming");
            setAnswer((prev) => prev + evt.text);
            break;
          case "sources":
            setCitations(evt.citations);
            break;
          case "error":
            terminated = true;
            setErrorMessage(evt.message);
            setStatus("error");
            break;
          case "done":
            terminated = true;
            setStatus((s) => (s === "error" ? "error" : "done"));
            break;
          default:
            setActivity((prev) => applyActivity(prev, evt));
        }
      }
      if (!terminated) {
        setErrorMessage("conexão interrompida");
        setStatus("error");
      }
    } catch (e) {
      if (genRef.current !== myGen) return;
      setErrorMessage(e instanceof Error ? e.message : "erro inesperado");
      setStatus("error");
    }
  }, []);

  return { status, answer, citations, activity, conversationId, errorMessage, ask, reset };
}
```

- [ ] **Step 4: Rodar os testes e o typecheck**

Run: `cd frontend && npx vitest run src/hooks/useAskStream.test.ts && npx tsc --noEmit`
Expected: PASS; `tsc` limpo.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAskStream.ts frontend/src/hooks/useAskStream.test.ts
git commit -m "feat(frontend): useAskStream expõe a linha do tempo (activity) e trata stream cortado

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: `TurnTimeline` no lugar do `ThinkingIndicator`

**Files:**
- Create: `frontend/src/features/chat/timelineLabels.ts`, `frontend/src/features/chat/components/TurnTimeline.tsx`, `frontend/src/features/chat/components/TurnTimeline.test.tsx`
- Modify: `frontend/src/features/chat/components/MessageBubble.tsx` (+ `.test.tsx`), `frontend/src/features/chat/components/MessageList.tsx`, `frontend/src/features/chat/ChatPage.tsx`, `frontend/src/features/chat/ChatPage.module.css`
- Delete: `frontend/src/features/chat/components/ThinkingIndicator.tsx`

**Interfaces:**
- Consumes: `ActivityItem` (Task 10).
- Produces: `stepLabel(name, detail?)`, `toolLabel(name, args?)`, `<TurnTimeline activity={ActivityItem[]} />`; `MessageBubble` e `MessageList` aceitam `activity?: ActivityItem[]`.

- [ ] **Step 1: Escrever os testes**

`frontend/src/features/chat/components/TurnTimeline.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ActivityItem } from "../../../hooks/useAskStream";
import { TurnTimeline } from "./TurnTimeline";

describe("TurnTimeline", () => {
  it("shows the waiting dots while there is no activity yet", () => {
    render(<TurnTimeline activity={[]} />);
    expect(screen.getByLabelText("Pensando")).toBeInTheDocument();
  });

  it("labels steps in Portuguese and shows the retrieval count", () => {
    const activity: ActivityItem[] = [
      { kind: "step", name: "gate", status: "done", detail: { retrieve: true, degraded: false } },
      { kind: "step", name: "retrieve", status: "done", detail: { kept: 4 } },
      { kind: "step", name: "answer", status: "running" },
    ];
    render(<TurnTimeline activity={activity} />);
    expect(screen.getByText("Entendendo a pergunta")).toBeInTheDocument();
    expect(screen.getByText("Buscando na base · 4 trechos")).toBeInTheDocument();
    expect(screen.getByText("Respondendo")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveAttribute("data-state", "done");
    expect(items[2]).toHaveAttribute("data-state", "running");
  });

  it("uses the singular for a single retrieved chunk and the refusal wording", () => {
    render(
      <TurnTimeline
        activity={[
          { kind: "step", name: "retrieve", status: "done", detail: { kept: 1 } },
          { kind: "step", name: "refuse", status: "done" },
        ]}
      />
    );
    expect(screen.getByText("Buscando na base · 1 trecho")).toBeInTheDocument();
    expect(screen.getByText("Nada na base cobre essa pergunta")).toBeInTheDocument();
  });

  it("shows the web search query but never the Notion page id", () => {
    const activity: ActivityItem[] = [
      { kind: "tool", id: "t1", name: "web_search", argsRaw: "", args: { query: "renovação PSP" }, status: "ok" },
      { kind: "tool", id: "t2", name: "fetch_notion_page", argsRaw: "", args: { page_id: "abc123-secret" }, status: "running" },
    ];
    render(<TurnTimeline activity={activity} />);
    expect(screen.getByText("Buscando na web: «renovação PSP»")).toBeInTheDocument();
    expect(screen.getByText("Lendo página do Notion")).toBeInTheDocument();
    expect(screen.queryByText(/abc123-secret/)).not.toBeInTheDocument();
  });

  it("marks a failed tool call", () => {
    render(
      <TurnTimeline
        activity={[{ kind: "tool", id: "t1", name: "web_search", argsRaw: "", status: "error" }]}
      />
    );
    const item = screen.getByRole("listitem");
    expect(item).toHaveAttribute("data-state", "error");
    expect(screen.getByText("falhou")).toBeInTheDocument();
  });
});
```

Acrescentar a `frontend/src/features/chat/components/MessageBubble.test.tsx`:

```tsx
  it("renders the turn timeline above the text while streaming, and not otherwise", () => {
    const activity = [{ kind: "step" as const, name: "answer", status: "running" as const }];
    const { rerender } = render(
      <MessageBubble role="assistant" content="parcial" streaming activity={activity} />
    );
    expect(screen.getByText("Respondendo")).toBeInTheDocument();

    rerender(<MessageBubble role="assistant" content="final" activity={activity} />);
    expect(screen.queryByText("Respondendo")).not.toBeInTheDocument();
  });

  it("does not blink a cursor on an empty streaming bubble", () => {
    const { container } = render(<MessageBubble role="assistant" content="" streaming activity={[]} />);
    expect(container.querySelector("[class*='cursor']")).toBeNull();
    expect(screen.getByLabelText("Pensando")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd frontend && npx vitest run src/features/chat/components/TurnTimeline.test.tsx src/features/chat/components/MessageBubble.test.tsx`
Expected: FAIL — `./TurnTimeline` não existe; `MessageBubble` não aceita `activity`.

- [ ] **Step 3: Implementar rótulos e componente**

`frontend/src/features/chat/timelineLabels.ts`:

```ts
/** Rótulos da linha do tempo do turno. Só aqui o nome técnico do passo/tool
 * vira frase para a pessoa. `fetch_notion_page` NÃO mostra o page_id: é ruído. */

export function stepLabel(name: string, detail?: Record<string, unknown>): string {
  switch (name) {
    case "gate":
      return "Entendendo a pergunta";
    case "retrieve": {
      const kept = detail?.kept;
      if (typeof kept === "number") return `Buscando na base · ${kept} ${kept === 1 ? "trecho" : "trechos"}`;
      return "Buscando na base";
    }
    case "refuse":
      return "Nada na base cobre essa pergunta";
    case "answer":
      return "Respondendo";
    default:
      return name;
  }
}

export function toolLabel(name: string, args?: Record<string, unknown>): string {
  switch (name) {
    case "web_search": {
      const query = args?.query;
      return typeof query === "string" && query ? `Buscando na web: «${query}»` : "Buscando na web";
    }
    case "fetch_notion_page":
      return "Lendo página do Notion";
    default:
      return name;
  }
}
```

`frontend/src/features/chat/components/TurnTimeline.tsx`:

```tsx
import type { ActivityItem } from "../../../hooks/useAskStream";
import { stepLabel, toolLabel } from "../timelineLabels";
import styles from "../ChatPage.module.css";

type State = "running" | "done" | "error";

function stateOf(item: ActivityItem): State {
  if (item.kind === "step") return item.status === "done" ? "done" : "running";
  if (item.status === "error") return "error";
  if (item.status === "ok") return "done";
  return "running";
}

/** Linha do tempo do turno (ADR-0019). Só existe enquanto o turno roda: o
 * ChatPage a monta do run_started até done/error. Sem atividade ainda (a fase 1
 * do backend não devolveu nada), mostra os três pontos de espera. */
export function TurnTimeline({ activity }: { activity: ActivityItem[] }) {
  if (activity.length === 0) {
    return (
      <div className={styles.thinking} role="status" aria-label="Pensando">
        <span /><span /><span />
      </div>
    );
  }
  return (
    <ol className={styles.timeline} aria-live="polite" aria-label="Andamento da resposta">
      {activity.map((item, i) => {
        const state = stateOf(item);
        const label = item.kind === "step" ? stepLabel(item.name, item.detail) : toolLabel(item.name, item.args);
        const key = item.kind === "tool" ? `tool-${item.id}` : `step-${item.name}-${i}`;
        return (
          <li key={key} className={styles.timelineItem} data-state={state}>
            <span className={styles.timelineDot} aria-hidden="true" />
            <span className={styles.timelineLabel}>{label}</span>
            {state === "error" && <span className={styles.timelineTag}>falhou</span>}
          </li>
        );
      })}
    </ol>
  );
}
```

Em `frontend/src/features/chat/ChatPage.module.css`, logo após a linha `@keyframes bounce { ... }` (linha 52), acrescentar:

```css
/* Linha do tempo do turno (ADR-0019): passos e tool calls ao vivo, acima do
   texto que está chegando. Some quando o turno termina. */
.timeline { list-style: none; margin: 0 0 var(--space-2); padding: 0; display: grid; gap: 4px; }
.timelineItem { display: flex; align-items: center; gap: 8px; font-size: .8rem; color: var(--text-muted); }
.timelineItem[data-state="done"] { color: var(--text); }
.timelineDot { width: 8px; height: 8px; border-radius: 50%; border: 2px solid var(--violet-ink); flex: none; box-sizing: border-box; }
.timelineItem[data-state="running"] .timelineDot { border-top-color: transparent; animation: spin 1s linear infinite; }
.timelineItem[data-state="done"] .timelineDot { background: var(--emerald-ink); border-color: var(--emerald-ink); }
.timelineItem[data-state="error"] .timelineDot { background: var(--danger-border); border-color: var(--danger-border); }
.timelineLabel { min-width: 0; overflow-wrap: anywhere; }
.timelineTag { font-family: var(--font-mono); font-size: .6rem; letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted); }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .timelineItem[data-state="running"] .timelineDot { animation: none; }
  .thinking span { animation: none; opacity: .7; }
}
```

- [ ] **Step 4: Ligar em `MessageBubble`, `MessageList` e `ChatPage`**

`frontend/src/features/chat/components/MessageBubble.tsx` (conteúdo completo):

```tsx
import ReactMarkdown from "react-markdown";
import type { Citation } from "../../../lib/types";
import type { ActivityItem } from "../../../hooks/useAskStream";
import { Logo } from "../../../components/Logo/Logo";
import { CitationsBlock } from "./CitationsBlock";
import { TurnTimeline } from "./TurnTimeline";
import { stripHtml, stripSourceMarkers } from "../../../lib/utils/text";
import { safeUrl } from "../../../lib/utils/safeUrl";
import styles from "../ChatPage.module.css";

type Props = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  /** Linha do tempo do turno em andamento — só faz sentido com `streaming`. */
  activity?: ActivityItem[];
};

export function MessageBubble({ role, content, citations, streaming, activity }: Props) {
  if (role === "user") {
    return <div className={styles.userTurn}><div className={styles.userBubble}>{content}</div></div>;
  }
  return (
    <div className={styles.botTurn}>
      <Logo size={34} />
      <div className={styles.botBody}>
        {streaming && activity && <TurnTimeline activity={activity} />}
        <div className={styles.botText}>
          <ReactMarkdown
            components={{
              a: ({ href, children }) => {
                const safe = href ? safeUrl(href) : null;
                return safe ? (
                  <a href={safe} target="_blank" rel="noreferrer">{children}</a>
                ) : (
                  <>{children}</>
                );
              },
              img: ({ alt }) => <>{alt ?? ""}</>,
            }}
          >
            {stripHtml(stripSourceMarkers(content))}
          </ReactMarkdown>
          {streaming && content && <span className={styles.cursor} />}
        </div>
        {citations && <CitationsBlock citations={citations} />}
      </div>
    </div>
  );
}
```

`frontend/src/features/chat/components/MessageList.tsx` (conteúdo completo):

```tsx
import type { Citation } from "../../../lib/types";
import type { ActivityItem } from "../../../hooks/useAskStream";
import { MessageBubble } from "./MessageBubble";

export type Turn = { id: string; role: "user" | "assistant"; content: string; citations?: Citation[] };

export function MessageList({
  turns,
  streamingIndex,
  activity,
}: {
  turns: Turn[];
  streamingIndex: number | null;
  activity?: ActivityItem[];
}) {
  return (
    <>
      {turns.map((t, i) => (
        <MessageBubble
          key={t.id}
          role={t.role}
          content={t.content}
          citations={t.citations}
          streaming={streamingIndex === i}
          activity={streamingIndex === i ? activity : undefined}
        />
      ))}
    </>
  );
}
```

Em `frontend/src/features/chat/ChatPage.tsx`:

- Remover `import { ThinkingIndicator } from "./components/ThinkingIndicator";`.
- Substituir o bloco:

```tsx
  const showThinking = stream.status === "thinking";
  const showError = stream.status === "error";
  const streamingIndex = stream.status === "streaming" ? turns.length - 1 : null;
  // While "thinking", hide the trailing empty assistant bubble entirely so the
  // ThinkingIndicator (which already renders its own Logo) is the only thing
  // shown — otherwise both render a Logo and it reads as a double-logo flash.
  const visibleTurns = showThinking ? turns.slice(0, -1) : turns;
```

por:

```tsx
  const showError = stream.status === "error";
  // A bolha final do assistente hospeda a linha do tempo do turno (ADR-0019)
  // desde o "thinking": vazia ela mostra os pontos de espera, depois os passos
  // e tool calls, depois o texto chegando. Não há mais indicador separado.
  const streamingIndex =
    stream.status === "thinking" || stream.status === "streaming" ? turns.length - 1 : null;
```

- Substituir:

```tsx
              <MessageList turns={visibleTurns} streamingIndex={streamingIndex} />
              {showThinking && <ThinkingIndicator />}
```

por:

```tsx
              <MessageList turns={turns} streamingIndex={streamingIndex} activity={stream.activity} />
```

Apagar `frontend/src/features/chat/components/ThinkingIndicator.tsx`.

- [ ] **Step 5: Rodar toda a suíte do frontend e o build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: todos os testes PASS (inclusive `App.test.tsx`, `architectureMap.test.ts`); build limpo.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat frontend/src/hooks
git commit -m "feat(frontend): TurnTimeline — passos e tool calls ao vivo na bolha do turno; remove ThinkingIndicator

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Docs finais e verificação completa

**Files:**
- Modify: `README.md:30`, `docs/architecture.md` (após o parágrafo "Consumo em duas fases", linha 515), `docs/superpowers/specs/2026-09-01-langgraph-langsmith-design.md` (final)

- [ ] **Step 1: README**

Linha 30 de `README.md`, trocar `which talks to the backend over HTTP/SSE.` por `which talks to the backend over HTTP/SSE using the AG-UI protocol (see ADR-0019).`

- [ ] **Step 2: `docs/architecture.md`**

Logo após o parágrafo que começa com `**Consumo em duas fases.**` (termina em `foram descartadas.`), acrescentar:

```markdown
**Contrato de saída: AG-UI (ADR-0019).** O que sai do runner não é texto cru: é uma união de dataclasses (`TextChunk`, `SourcesChunk`, `StepChunk`, `ToolCall*Chunk`, em `src/support/agent/ports.py`) que um `TurnEmitter` sintetiza a partir dos `updates` (um passo por nó; `ToolMessage` vira result só com status) e dos `messages` (texto e `tool_call_chunks` do nó `answer`). A tradução para eventos do protocolo AG-UI — `RUN_STARTED`, `STEP_*`, `TOOL_CALL_*`, `TEXT_MESSAGE_*`, `CUSTOM oracle.step`/`oracle.sources`, `RUN_FINISHED`/`RUN_ERROR` — mora em `src/app/api/streaming/ag_ui_encoder.py`, na camada `app`; o body do endpoint é o `RunAgentInput` (`src/app/api/requests/run_agent_request.py`). Domínio e grafo não importam `ag_ui` (teste de fronteira). Consequência das duas fases: `RUN_STARTED` e os passos `gate`/`retrieve` chegam ao cliente numa rajada com o primeiro token.
```

- [ ] **Step 3: Nota na spec do LangGraph**

Ao final de `docs/superpowers/specs/2026-09-01-langgraph-langsmith-design.md`, acrescentar:

```markdown

---

**Nota (2026-09-04).** O contrato de saída do runner mudou com a spec
`2026-09-04-ag-ui-turno-design.md` / ADR-0019: `AgentStreamChunk` virou uma
união com passos e tool calls, e o controller passou a emitir eventos AG-UI. O
consumo em duas fases (seção 5) e o tratamento de falhas (seção 7) descritos
aqui continuam valendo.
```

- [ ] **Step 4: Verificação completa**

Run, na raiz:

```bash
uv run pytest -q
uv run prospector
uv run alembic check
uv run python -c "from main import app; print('OK')"
```

Expected: pytest verde; prospector sem novos achados nos arquivos tocados; `alembic check` "No new upgrade operations detected"; `OK`.

Run, em `frontend/`:

```bash
npx vitest run && npm run build
```

Expected: verde e build limpo.

Verificação manual (com backend e frontend em dev, `.env` configurado):

1. Perguntar algo substantivo: a bolha mostra "Entendendo a pergunta" → "Buscando na base · N trechos" → "Respondendo" → texto → fontes; a linha do tempo some ao terminar.
2. Perguntar algo que dispara `web_search`: "Buscando na web: «…»" aparece entre os momentos de resposta.
3. Perguntar algo fora de escopo: "Nada na base cobre essa pergunta" e texto canônico, sem fontes.
4. `curl` direto:

```bash
curl -N -H 'Content-Type: application/json' -H 'Accept: text/event-stream' \
  -H "Cookie: ob_session=$TOKEN" http://localhost:8000/conversations/ask \
  -d "{\"threadId\":\"$(uuidgen)\",\"runId\":\"$(uuidgen)\",\"messages\":[{\"id\":\"m1\",\"role\":\"user\",\"content\":\"o que é PSP?\"}],\"tools\":[],\"context\":[],\"forwardedProps\":{}}"
```

Expected: linhas `data: {"type":"RUN_STARTED",...}` até `data: {"type":"RUN_FINISHED",...}`; nenhum `event:`; nenhum `<<TOOL_CONTENT>>`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/architecture.md docs/superpowers/specs/2026-09-01-langgraph-langsmith-design.md
git commit -m "docs: arquitetura e README apontam para o contrato AG-UI do turno (ADR-0019)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review (feito ao escrever)

- **Cobertura da spec:** §1 entrada (Task 6, 8) e saída (Task 7, 8); §2 ports (Task 2); §3.1–3.3 runner (Tasks 3, 4); §4 Action (Task 5); §5 request/encoder/controller (Tasks 6, 7, 8); §6 frontend (Tasks 9, 10, 11); §7 falhas (Task 8 testes de erro/422/404; Task 10 stream cortado); §9 dependência (Task 1); §10 testes (distribuídos; fronteira em Task 2; eval em Task 2); §11 sequência de corte (ordem das tasks; ADR primeiro; mapa no mesmo commit em Task 8); §12 aceite (Task 12).
- **Divergência da spec corrigida:** thread alheia é **404**, não 403 (`ConversationAccessPolicy` lança `NotFoundError`, ADR-0017). A spec foi ajustada.
- **Consistência de nomes:** `TurnEmitter.on_update/on_message/finish` (Tasks 3, 4); `RunContext`, `to_events`, `run_started/run_finished/run_error`, `encode`, `CONTENT_TYPE`, `SOURCES_EVENT`, `STEP_EVENT` (Tasks 7, 8); `RunAgentRequest.question/conversation_id/run_id` (Tasks 6, 8); `AskEvent` com `run_started.conversationId` (Tasks 9, 10, demo); `ActivityItem/StepItem/ToolItem/applyActivity` (Tasks 10, 11); `parseSSEData` (Task 9); `buildRunAgentInput/parseAgUiStream/toAskEvents` (Task 9).
