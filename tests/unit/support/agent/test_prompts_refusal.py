"""O prompt tem de carregar a cópia exata da recusa, senão a camada 2 improvisa."""

from src.domain.conversations.services.out_of_scope_reply import OUT_OF_SCOPE_OPENING_PT
from src.support.agent.prompts import SYSTEM_PROMPT


def test_prompt_contains_the_literal_refusal_opening():
    assert OUT_OF_SCOPE_OPENING_PT in SYSTEM_PROMPT


def test_prompt_instructs_to_use_it_verbatim():
    assert "literalmente" in SYSTEM_PROMPT.lower()


def test_prompt_contains_the_english_refusal_contiguously():
    english_refusal = "I didn't find information about this in the knowledge base."
    assert english_refusal in SYSTEM_PROMPT


def test_prompt_carves_out_conversational_turns():
    """Conversational turns (greetings, thanks, oracle questions) must not trigger refusal."""
    assert "saudações" in SYSTEM_PROMPT.lower()
    assert "agradecimentos" in SYSTEM_PROMPT.lower()


def test_prompt_proibe_marcador_de_fonte_no_texto_da_resposta():
    """A interface exibe as fontes no bloco recolhível; o modelo não pode copiar
    o marcador `[Fonte: …]` (que vem do contexto das ferramentas) para o texto."""
    assert "[Fonte:" in SYSTEM_PROMPT  # o marcador é nomeado explicitamente…
    assert "não escreva" in SYSTEM_PROMPT.lower() or "nunca escreva" in SYSTEM_PROMPT.lower()
    assert "sempre cite as fontes" not in SYSTEM_PROMPT.lower()  # …e a regra antiga sumiu
