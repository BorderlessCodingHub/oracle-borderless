"""As três decisões do turno, isoladas. Antes viviam soldadas dentro de
AnswerQuestionAction e só podiam ser exercitadas pelo caminho completo."""

from src.domain.shared.value_objects.citation import Citation
from src.support.agent.graph.edges import has_grounding, route_entry, should_retrieve
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


# --- should_retrieve -----------------------------------------------------

def test_a_substantive_question_goes_to_retrieval():
    assert should_retrieve({"retrieve": True}) == "retrieve"


def test_a_greeting_goes_straight_to_the_answer():
    """retrieve=False não injeta contexto nenhum — sem poluição de prompt."""
    assert should_retrieve({"retrieve": False}) == "answer"


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
