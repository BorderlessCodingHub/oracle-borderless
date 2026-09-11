"""Cada nó isolado, com dependências fakes. Antes gate e retrieval estavam
soldados dentro de AnswerQuestionAction e não podiam ser testados sozinhos."""

import asyncio

import pytest

from src.support.agent.graph.nodes import gate_node
from src.support.agent.ports import TurnDependencies, TurnSignals


class _FakeStructuredModel:
    """Imita o retorno de model.with_structured_output(...)."""

    def __init__(self, output=None, raises=None, delay=0.0):
        self._output = output
        self._raises = raises
        self._delay = delay
        self.prompt = None

    async def ainvoke(self, messages):
        self.prompt = messages
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return self._output


def _config(signals, model, deps=None):
    return {"configurable": {"signals": signals, "deps": deps, "gate_model": model}}


@pytest.mark.asyncio
async def test_a_substantive_question_asks_for_retrieval_with_a_rewritten_query():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=True, search_query="renovação de PSP"))

    out = await gate_node(
        {"question": "e as renovações?", "history": []}, _config(signals, model)
    )

    assert out["retrieve"] is True
    assert out["search_query"] == "renovação de PSP"
    assert out["degraded"] is False
    assert signals.gate_retrieve is True
    assert signals.gate_search_query == "renovação de PSP"


@pytest.mark.asyncio
async def test_a_greeting_skips_retrieval():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=False, search_query=""))

    out = await gate_node({"question": "valeu!", "history": []}, _config(signals, model))

    assert out["retrieve"] is False
    assert out["search_query"] == ""
    assert signals.gate_degraded is False


@pytest.mark.asyncio
async def test_an_empty_rewritten_query_falls_back_to_the_raw_question():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=True, search_query="   "))

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["search_query"] == "o que é PSP?"


@pytest.mark.asyncio
async def test_a_failing_gate_fails_open_and_marks_the_turn_degraded():
    signals = TurnSignals()
    model = _FakeStructuredModel(raises=RuntimeError("provider caiu"))

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["retrieve"] is True
    assert out["search_query"] == "o que é PSP?"
    assert out["degraded"] is True
    assert signals.gate_degraded is True


@pytest.mark.asyncio
async def test_a_slow_gate_times_out_and_fails_open(monkeypatch):
    from src.support.core.settings import settings

    monkeypatch.setattr(settings, "GATE_TIMEOUT_SECONDS", 0.01)
    signals = TurnSignals()
    model = _FakeStructuredModel(output=None, delay=0.5)

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["degraded"] is True
    assert out["retrieve"] is True


@pytest.mark.asyncio
async def test_a_navigation_intent_is_classified_and_never_retrieves():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=False, search_query="", intent="navigate"))

    out = await gate_node(
        {"question": "quero praticar algoritmos", "history": []}, _config(signals, model)
    )

    assert out["intent"] == "navigate"
    assert out["retrieve"] is False
    assert signals.intent == "navigate"


@pytest.mark.asyncio
async def test_a_navigation_intent_normalizes_retrieve_to_false_even_if_the_model_said_true():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=True, search_query="algo", intent="navigate"))

    out = await gate_node(
        {"question": "me leva para as trilhas de backend", "history": []}, _config(signals, model)
    )

    assert out["intent"] == "navigate"
    assert out["retrieve"] is False
    assert out["search_query"] == ""


@pytest.mark.asyncio
async def test_a_failing_gate_carries_a_knowledge_intent():
    signals = TurnSignals()
    model = _FakeStructuredModel(raises=RuntimeError("provider caiu"))

    out = await gate_node({"question": "o que é PSP?", "history": []}, _config(signals, model))

    assert out["intent"] == "knowledge"
    assert out["degraded"] is True
    assert signals.intent == "knowledge"


@pytest.mark.asyncio
async def test_the_gate_always_records_its_latency():
    from src.support.agent.graph.nodes import _GateOutput

    signals = TurnSignals()
    model = _FakeStructuredModel(_GateOutput(retrieve=False, search_query=""))

    await gate_node({"question": "oi", "history": []}, _config(signals, model))

    assert signals.gate_ms >= 0


# --- retrieve / refuse ---------------------------------------------------

from src.domain.shared.value_objects.citation import Citation  # noqa: E402
from src.support.agent.graph.nodes import refuse_node, retrieve_node  # noqa: E402
from src.support.agent.ports import KnowledgeSnippet  # noqa: E402


def _snippet(text="conteúdo"):
    return KnowledgeSnippet(
        content=text,
        citation=Citation(source_type="notion", title="Doc", url="https://n", snippet=text[:200]),
    )


class _FakeSearch:
    def __init__(self, snippets=None, raises=None):
        self._snippets = snippets or []
        self._raises = raises
        self.query = None
        self.calls = 0

    async def execute(self, query, top_k=None):
        self.calls += 1
        self.query = query
        if self._raises is not None:
            raise self._raises
        return self._snippets


class _FakeSections:
    def __init__(self, sections=None):
        self._sections = sections or ["PSP", "Borderless Tech"]

    async def execute(self):
        return self._sections


class _FakeNearest:
    def __init__(self, distance=0.61, raises=None):
        self._distance = distance
        self._raises = raises

    async def execute(self, query):
        if self._raises is not None:
            raise self._raises
        return self._distance


def _deps(search=None, sections=None, nearest=None):
    from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply

    return TurnDependencies(
        search=search or _FakeSearch(),
        sections=sections or _FakeSections(),
        refusal=build_out_of_scope_reply,
        nearest=nearest,
    )


@pytest.mark.asyncio
async def test_retrieval_uses_the_query_the_gate_rewrote():
    search = _FakeSearch([_snippet()])
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=search)}}

    out = await retrieve_node({"search_query": "renovação de PSP"}, config)

    assert search.query == "renovação de PSP"
    assert len(out["knowledge"]) == 1


@pytest.mark.asyncio
async def test_retrieval_records_its_signal():
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=_FakeSearch([_snippet(), _snippet()]))}}

    await retrieve_node({"search_query": "q"}, config)

    assert signals.retrieval_ran is True
    assert signals.retrieval_kept == 2
    assert signals.retrieval_ms is not None
    assert signals.retrieval_top_k > 0
    assert signals.retrieval_threshold > 0


@pytest.mark.asyncio
async def test_the_refusal_is_deterministic_and_calls_no_model():
    from src.domain.conversations.services.out_of_scope_reply import OUT_OF_SCOPE_OPENING_PT

    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps()}}

    out = await refuse_node({"question": "quanto custa um carro?", "search_query": "carro"}, config)

    assert out["answer"].startswith(OUT_OF_SCOPE_OPENING_PT)
    assert out["citations"] == []
    assert out["outcome"] == "refusal"
    assert signals.outcome == "refusal"


@pytest.mark.asyncio
async def test_the_refusal_records_the_nearest_distance_for_the_trace():
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(nearest=_FakeNearest(0.61))}}

    await refuse_node({"question": "q", "search_query": "q"}, config)

    assert signals.retrieval_best_distance == 0.61


@pytest.mark.asyncio
async def test_a_failing_distance_probe_never_costs_the_user_the_refusal():
    """Observabilidade não derruba turno: sem distância é melhor que sem recusa."""
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(nearest=_FakeNearest(raises=RuntimeError("pgvector fora")))}}

    out = await refuse_node({"question": "q", "search_query": "q"}, config)

    assert out["outcome"] == "refusal"
    assert signals.retrieval_best_distance is None


# --- answer --------------------------------------------------------------

from langchain_core.messages import AIMessage  # noqa: E402

from src.support.agent.graph.nodes import answer_node  # noqa: E402


class _FakeChatModel:
    def __init__(self, message=None):
        self._message = message or AIMessage(content="resposta do oráculo")
        self.received = None

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.received = messages
        return self._message


def _answer_config(signals, deps=None, model=None, citations=None):
    return {
        "configurable": {
            "signals": signals,
            "deps": deps or _deps(),
            "answer_model": model or _FakeChatModel(),
            "citations": citations if citations is not None else [],
        }
    }


@pytest.mark.asyncio
async def test_the_answer_node_marks_the_turn_as_answered():
    signals = TurnSignals()
    out = await answer_node({"question": "q", "history": [], "knowledge": []}, _answer_config(signals))

    assert out["outcome"] == "answer"
    assert signals.outcome == "answer"


@pytest.mark.asyncio
async def test_retrieved_knowledge_reaches_the_prompt_wrapped_as_untrusted():
    model = _FakeChatModel()
    signals = TurnSignals()
    state = {"question": "o que é PSP?", "history": [], "knowledge": [_snippet("PSP é um programa")]}

    await answer_node(state, _answer_config(signals, model=model))

    prompt = "\n".join(str(m) for m in model.received)
    assert "PSP é um programa" in prompt
    assert "<<TOOL_CONTENT>>" in prompt


@pytest.mark.asyncio
async def test_citations_combine_the_knowledge_base_and_the_web():
    web = [Citation(source_type="web", title="W", url="https://w", snippet="s")]
    signals = TurnSignals()
    state = {"question": "q", "history": [], "knowledge": [_snippet()]}

    out = await answer_node(state, _answer_config(signals, citations=web))

    kinds = sorted(c.source_type for c in out["citations"])
    assert kinds == ["notion", "web"]


@pytest.mark.asyncio
async def test_missing_usage_metadata_leaves_the_trace_without_tokens():
    """Observabilidade nunca derruba um turno."""
    signals = TurnSignals()
    model = _FakeChatModel(AIMessage(content="ok"))  # sem usage_metadata

    await answer_node({"question": "q", "history": [], "knowledge": []}, _answer_config(signals, model=model))

    assert signals.input_tokens is None
    assert signals.output_tokens is None


@pytest.mark.asyncio
async def test_usage_metadata_fills_the_token_columns():
    signals = TurnSignals()
    message = AIMessage(content="ok", usage_metadata={"input_tokens": 120, "output_tokens": 34, "total_tokens": 154})

    await answer_node(
        {"question": "q", "history": [], "knowledge": []},
        _answer_config(signals, model=_FakeChatModel(message)),
    )

    assert signals.input_tokens == 120
    assert signals.output_tokens == 34


@pytest.mark.asyncio
async def test_the_first_entry_puts_the_full_prompt_in_the_state_alongside_the_reply():
    """Sem isto, a re-entrada do tool loop (answer -> tools -> answer) só
    acharia [AIMessage(tool_calls), ToolMessage] no state — o reducer
    add_messages não reconstrói o que não foi devolvido aqui."""
    from langchain_core.messages import SystemMessage

    reply = AIMessage(content="resposta final")
    model = _FakeChatModel(reply)
    signals = TurnSignals()
    state = {"question": "o que é PSP?", "history": [], "knowledge": []}

    out = await answer_node(state, _answer_config(signals, model=model))

    assert any(isinstance(m, SystemMessage) for m in out["messages"])
    assert any("o que é PSP?" in str(m.content) for m in out["messages"])
    assert out["messages"][-1] is reply


@pytest.mark.asyncio
async def test_a_tool_loop_reentry_reuses_the_state_messages_and_returns_only_the_new_reply():
    from langchain_core.messages import ToolMessage

    prior = [
        AIMessage(
            content="",
            tool_calls=[{"name": "web_search", "args": {"query": "q"}, "id": "call-1"}],
        ),
        ToolMessage(content="resultado da tool", tool_call_id="call-1"),
    ]
    reply = AIMessage(content="resposta final")
    model = _FakeChatModel(reply)
    signals = TurnSignals()
    state = {"question": "q", "history": [], "knowledge": [], "messages": prior}

    out = await answer_node(state, _answer_config(signals, model=model))

    assert model.received == prior
    assert out["messages"] == [reply]


# --- profile, locale and navigation intent in the answer prompt ----------


def test_answer_messages_builds_profile_locale_and_navigation_lines():
    from src.support.agent.graph.nodes import _answer_messages

    state = {"question": "q", "history": [], "knowledge": [], "locale": "en", "intent": "navigate"}
    config = {
        "configurable": {
            "user_profile": {
                "membership": "FREE",
                "seniority": "JUNIOR",
                "careerStage": "junior_transition",
            }
        }
    }

    human = str(_answer_messages(state, config)[-1].content)

    assert "Idioma da resposta: en" in human
    assert "membership=FREE" in human
    assert "Intenção: navegação" in human


def test_answer_messages_with_a_knowledge_intent_has_no_navigation_marker():
    from src.support.agent.graph.nodes import _answer_messages

    human = str(
        _answer_messages(
            {"question": "q", "history": [], "knowledge": [], "intent": "knowledge"}, {"configurable": {}}
        )[-1].content
    )

    assert "Intenção: navegação" not in human


def test_answer_messages_skips_the_profile_line_when_absent():
    from src.support.agent.graph.nodes import _answer_messages

    human = str(_answer_messages({"question": "q", "history": [], "knowledge": []}, {"configurable": {}})[-1].content)

    assert "Perfil do usuário" not in human
    assert "Idioma da resposta: pt-BR" in human


@pytest.mark.asyncio
async def test_answer_node_passes_the_full_config_through_to_the_prompt():
    """answer_node precisa repassar `config` (não só `cfg`) para
    `_answer_messages` — senão user_profile e locale nunca chegam ao prompt."""
    model = _FakeChatModel()
    signals = TurnSignals()
    config = _answer_config(signals, model=model)
    config["configurable"]["user_profile"] = {
        "membership": "PRO",
        "seniority": "SENIOR",
        "careerStage": "already_global",
    }
    state = {"question": "q", "history": [], "knowledge": [], "locale": "es"}

    await answer_node(state, config)

    prompt = "\n".join(str(m) for m in model.received)
    assert "membership=PRO" in prompt
    assert "Idioma da resposta: es" in prompt


class _FakeSearchByQuery:
    """Devolve snippets por query — simula reescrita que embeda pior que a pergunta."""

    def __init__(self, by_query):
        self._by_query = by_query
        self.queries = []

    async def execute(self, query, top_k=None):
        self.queries.append(query)
        return self._by_query.get(query, [])


@pytest.mark.asyncio
async def test_a_rewrite_that_keeps_nothing_falls_back_to_the_raw_question():
    search = _FakeSearchByQuery({"O que é a mentoria a base?": [_snippet()]})
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=search)}}

    out = await retrieve_node(
        {"question": "O que é a mentoria a base?", "search_query": "mentoria da base"}, config
    )

    assert search.queries == ["mentoria da base", "O que é a mentoria a base?"]
    assert len(out["knowledge"]) == 1
    assert out["search_query"] == "O que é a mentoria a base?"
    assert signals.retrieval_kept == 1


@pytest.mark.asyncio
async def test_a_fallback_that_also_keeps_nothing_still_refuses():
    search = _FakeSearchByQuery({})
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=search)}}

    out = await retrieve_node({"question": "pergunta", "search_query": "reescrita"}, config)

    assert search.queries == ["reescrita", "pergunta"]
    assert out["knowledge"] == []
    assert signals.retrieval_kept == 0


@pytest.mark.asyncio
async def test_a_rewrite_equal_to_the_question_never_searches_twice():
    search = _FakeSearchByQuery({})
    signals = TurnSignals()
    config = {"configurable": {"signals": signals, "deps": _deps(search=search)}}

    await retrieve_node({"question": "pergunta", "search_query": "pergunta"}, config)

    assert search.queries == ["pergunta"]


# --- R12: navegação só para sessões que sabem navegar (ADR-0022) ----------


class _ToolRecordingChatModel(_FakeChatModel):
    """Guarda as tools ligadas — é o que prova que `navigate_platform` não foi
    oferecida a um cliente que não sabe executar redirect."""

    def __init__(self, message=None):
        super().__init__(message)
        self.bound: list = []

    def bind_tools(self, tools):
        self.bound = [t.name for t in tools]
        return self


@pytest.mark.asyncio
async def test_without_navigation_enabled_the_model_never_sees_navigate_platform():
    model = _ToolRecordingChatModel()
    config = _answer_config(TurnSignals(), model=model)

    await answer_node({"question": "q", "history": [], "knowledge": []}, config)

    assert "navigate_platform" not in model.bound
    assert {"web_search", "fetch_notion_page"} == set(model.bound)


@pytest.mark.asyncio
async def test_with_navigation_enabled_the_model_sees_navigate_platform():
    model = _ToolRecordingChatModel()
    config = _answer_config(TurnSignals(), model=model)
    config["configurable"]["navigation_enabled"] = True

    await answer_node({"question": "q", "history": [], "knowledge": []}, config)

    assert "navigate_platform" in model.bound


# --- C4b: mode="mentor" liga só search_lesson ao modelo -------------------


@pytest.mark.asyncio
async def test_mentor_mode_binds_only_search_lesson():
    model = _ToolRecordingChatModel()
    config = _answer_config(TurnSignals(), model=model)

    await answer_node({"question": "q", "history": [], "knowledge": [], "mode": "mentor"}, config)

    assert set(model.bound) == {"search_lesson"}


@pytest.mark.asyncio
async def test_chat_mode_keeps_the_oracle_tools_unchanged():
    """Mesma asserção de `test_without_navigation_enabled_the_model_never_sees_navigate_platform`,
    agora explícita sobre `mode`: passar por `_answer_model(mode=...)` não pode
    mudar o conjunto de tools do chat comum."""
    model = _ToolRecordingChatModel()
    config = _answer_config(TurnSignals(), model=model)

    await answer_node({"question": "q", "history": [], "knowledge": [], "mode": "chat"}, config)

    assert set(model.bound) == {"web_search", "fetch_notion_page"}


def test_the_system_message_carries_the_navigation_block_only_when_enabled():
    from src.support.agent.graph.nodes import _answer_messages

    state = {"question": "q", "history": [], "knowledge": []}
    off = str(_answer_messages(state, {"configurable": {}})[0].content)
    on = str(_answer_messages(state, {"configurable": {"navigation_enabled": True}})[0].content)

    assert "NAVEGAÇÃO" not in off and "navigate_platform" not in off
    assert "NAVEGAÇÃO" in on and "navigate_platform" in on
