"""Bloco de NAVEGAÇÃO no prompt: quando e como chamar `navigate_platform`, sem
contradizer a regra 1 (grounding) para intents que não são pergunta substantiva."""

from src.support.agent.prompts import SYSTEM_PROMPT


def test_prompt_has_a_navigation_section_naming_the_tool():
    assert "NAVEGAÇÃO" in SYSTEM_PROMPT
    assert "navigate_platform" in SYSTEM_PROMPT


def test_prompt_forbids_inventing_destinations():
    assert "Nunca invente destinos" in SYSTEM_PROMPT


def test_rule_one_is_scoped_to_substantive_questions():
    """Regra 1 original ("Responda SOMENTE com base...") se aplicava a QUALQUER
    pergunta, inclusive navegação/conversa — o que contradiz o bloco de
    NAVEGAÇÃO. A emenda restringe a regra 1 às perguntas substantivas."""
    assert "Para perguntas substantivas sobre o ecossistema, responda SOMENTE" in SYSTEM_PROMPT


def test_navigation_does_not_require_retrieved_context():
    """O bloco de NAVEGAÇÃO precisa deixar explícito que navegar/conversar não
    exige contexto da base, senão o modelo tenta aplicar a RESPOSTA PADRÃO
    (grounding) também para navegação — a contradição que este teste evita."""
    assert "não exige contexto da base" in SYSTEM_PROMPT.lower()
    assert "nunca use a resposta padrão" in SYSTEM_PROMPT.lower()
