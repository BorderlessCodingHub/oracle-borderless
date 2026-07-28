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
