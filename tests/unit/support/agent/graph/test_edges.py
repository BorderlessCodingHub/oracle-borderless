"""As três decisões do turno, isoladas. Antes viviam soldadas dentro de
AnswerQuestionAction e só podiam ser exercitadas pelo caminho completo."""

from langchain_core.messages import AIMessage
from langgraph.graph import END

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.edges import (
    after_answer,
    has_grounding,
    route_entry,
    should_retrieve,
)
from src.support.agent.ports import KnowledgeSnippet


def _snippet(text="conteúdo"):
    return KnowledgeSnippet(
        content=text,
        citation=Citation(source_type="notion", title="Doc", url="https://n", snippet=text[:200]),
    )


# --- route_entry ---------------------------------------------------------

def test_preset_knowledge_skips_straight_to_the_answer():
    """Caso adversarial do eval: contexto envenenado injetado à mão, sem gate."""
    assert route_entry({"preset_knowledge": True, "knowledge": [_snippet()]}) == "answer"


def test_a_normal_turn_starts_at_the_gate():
    assert route_entry({"preset_knowledge": False, "knowledge": []}) == "gate"


def test_a_missing_preset_flag_starts_at_the_gate():
    assert route_entry({}) == "gate"


def test_navigate_mode_skips_the_gate():
    assert route_entry({"mode": "navigate", "intent": "navigate"}) == "answer"


def test_mentor_mode_skips_the_gate():
    from src.support.agent.graph.edges import route_entry

    assert route_entry({"mode": "mentor"}) == "answer"


def test_chat_mode_still_reaches_the_gate():
    from src.support.agent.graph.edges import route_entry

    assert route_entry({"mode": "chat"}) == "gate"


# --- should_retrieve -----------------------------------------------------

def test_a_substantive_question_goes_to_retrieval():
    assert should_retrieve({"retrieve": True}) == "retrieve"


def test_a_greeting_goes_straight_to_the_answer():
    """retrieve=False não injeta contexto nenhum — sem poluição de prompt."""
    assert should_retrieve({"retrieve": False}) == "answer"


def test_a_navigation_intent_never_retrieves_even_if_the_gate_said_so():
    assert should_retrieve({"retrieve": True, "intent": "navigate"}) == "answer"


def test_chit_chat_never_retrieves():
    assert should_retrieve({"retrieve": True, "intent": "chit_chat"}) == "answer"


def test_a_knowledge_intent_keeps_retrieving():
    assert should_retrieve({"retrieve": True, "intent": "knowledge"}) == "retrieve"
    assert should_retrieve({"retrieve": True}) == "retrieve"  # compat: sem intent = knowledge


# --- has_grounding -------------------------------------------------------

def test_retrieved_context_goes_to_the_answer():
    assert has_grounding({"knowledge": [_snippet()], "degraded": False}) == "answer"


def test_nothing_above_the_threshold_refuses():
    """Recusa determinística, sem chamar o LLM."""
    assert has_grounding({"knowledge": [], "degraded": False}) == "refuse"


def test_a_degraded_gate_never_refuses():
    """O caso sutil, e o motivo de esta aresta existir.

    Gate degradado = erro ou timeout: ele NUNCA classificou o turno, então o
    retrieve=True dali é chute de fail-open, não decisão fundamentada. Recusar
    seria injustificado — imagine "oi" durante um timeout do gate. Vai ao motor
    com o knowledge que houver, possivelmente vazio.
    """
    assert has_grounding({"knowledge": [], "degraded": True}) == "answer"


def test_a_degraded_gate_with_context_also_answers():
    assert has_grounding({"knowledge": [_snippet()], "degraded": True}) == "answer"


# --- after_answer --------------------------------------------------------


def test_after_answer_routes_navigate_calls_to_the_navigate_node():
    msg = AIMessage(content="", tool_calls=[{"name": "navigate_platform", "args": {"destination": "home"}, "id": "1", "type": "tool_call"}])
    assert after_answer({"messages": [msg]}) == "navigate"


def test_after_answer_routes_other_tool_calls_to_tools():
    msg = AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "q"}, "id": "1", "type": "tool_call"}])
    assert after_answer({"messages": [msg]}) == "tools"


def test_after_answer_ends_without_tool_calls():
    assert after_answer({"messages": [AIMessage(content="pronto")]}) == END


def test_after_answer_ends_on_an_empty_state():
    assert after_answer({}) == END


def test_a_navigate_call_mixed_with_others_still_goes_to_the_navigate_node():
    """O nó `navigate` responde a TODAS as tool calls da mensagem — as outras
    recebem ToolMessage de erro. Mandar ao ToolNode deixaria a navigate call
    sem resposta e o provider recusaria o próximo turno."""
    msg = AIMessage(content="", tool_calls=[
        {"name": "web_search", "args": {"query": "q"}, "id": "1", "type": "tool_call"},
        {"name": "navigate_platform", "args": {"destination": "home"}, "id": "2", "type": "tool_call"},
    ])
    assert after_answer({"messages": [msg]}) == "navigate"
