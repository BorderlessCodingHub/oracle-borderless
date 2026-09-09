"""Bloco de NAVEGAÇÃO no prompt: quando e como chamar `navigate_platform`, sem
contradizer a regra 1 (grounding) para intents que não são pergunta substantiva.

R12 (ADR-0022): o bloco é montado só para sessões que sabem navegar — o prompt
base fica igual para o SPA do oráculo, que não executa redirect."""

from src.support.agent.prompts import NAVIGATION_PROMPT_BLOCK, SYSTEM_PROMPT, build_system_prompt


def test_navigation_block_names_the_tool():
    assert "NAVEGAÇÃO" in NAVIGATION_PROMPT_BLOCK
    assert "navigate_platform" in NAVIGATION_PROMPT_BLOCK


def test_navigation_block_forbids_inventing_destinations():
    assert "Nunca invente destinos" in NAVIGATION_PROMPT_BLOCK


def test_rule_one_is_scoped_to_substantive_questions():
    """Regra 1 original ("Responda SOMENTE com base...") se aplicava a QUALQUER
    pergunta, inclusive navegação/conversa — o que contradiz o bloco de
    NAVEGAÇÃO. A emenda restringe a regra 1 às perguntas substantivas, e fica no
    prompt base: é inofensiva sem navegação e continua valendo para conversa."""
    assert "Para perguntas substantivas sobre o ecossistema, responda SOMENTE" in SYSTEM_PROMPT


def test_navigation_does_not_require_retrieved_context():
    """O bloco de NAVEGAÇÃO precisa deixar explícito que navegar/conversar não
    exige contexto da base, senão o modelo tenta aplicar a RESPOSTA PADRÃO
    (grounding) também para navegação — a contradição que este teste evita."""
    assert "não exige contexto da base" in NAVIGATION_PROMPT_BLOCK.lower()
    assert "nunca use a resposta padrão" in NAVIGATION_PROMPT_BLOCK.lower()


def test_base_prompt_has_no_navigation_block():
    """O SPA do oráculo não navega: descrever a tool para ele seria prometer uma
    ação que aquele cliente não executa."""
    assert "NAVEGAÇÃO" not in SYSTEM_PROMPT
    assert "navigate_platform" not in SYSTEM_PROMPT


def test_build_system_prompt_appends_the_block_only_when_navigation_is_enabled():
    assert build_system_prompt(True) == SYSTEM_PROMPT + NAVIGATION_PROMPT_BLOCK
    assert build_system_prompt(False) == SYSTEM_PROMPT
    assert "navigate_platform" not in build_system_prompt(False)
