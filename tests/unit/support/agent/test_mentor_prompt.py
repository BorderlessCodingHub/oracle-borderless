from src.support.agent.prompts import MENTOR_PROMPT, build_system_prompt


def test_mentor_mode_gets_the_mentor_prompt_not_the_oracle_one():
    prompt = build_system_prompt(navigation_enabled=False, mode="mentor")
    assert prompt == MENTOR_PROMPT


def test_the_mentor_never_receives_the_standard_refusal():
    """O mentor pula o gate e não recusa (spec §3, passo 5); herdar a RESPOSTA
    PADRÃO do oráculo reintroduziria a recusa pela porta do prompt."""
    prompt = build_system_prompt(navigation_enabled=False, mode="mentor")
    assert "Não encontrei informações sobre isso na base de conhecimento" not in prompt


def test_the_mentor_is_told_to_separate_the_lesson_from_its_own_knowledge():
    prompt = MENTOR_PROMPT.lower()
    assert "complement" in prompt
    assert "a aula" in prompt


def test_the_mentor_keeps_the_anti_injection_rule():
    assert "<<TOOL_CONTENT>>" in MENTOR_PROMPT


def test_other_modes_are_untouched():
    assert build_system_prompt(navigation_enabled=False, mode="chat").startswith("Você é o Oracle Borderless")
    assert build_system_prompt(navigation_enabled=False).startswith("Você é o Oracle Borderless")
