from src.domain.conversations.services.out_of_scope_reply import (
    build_out_of_scope_reply,
    detect_language,
)

SECOES = ["Bootcamps", "Conferences", "Masterclasses", "Mentorship", "Programs"]


def test_detects_portuguese():
    assert detect_language("qual é o processo de renovação do PSP?") == "pt"


def test_detects_english():
    assert detect_language("what is the renewal process for PSP?") == "en"


def test_defaults_to_portuguese_when_ambiguous():
    assert detect_language("PSP?") == "pt"
    assert detect_language("") == "pt"


def test_portuguese_copy_lists_every_section():
    text = build_out_of_scope_reply(SECOES, "qual é o processo de renovação?")
    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    for secao in SECOES:
        assert secao in text
    assert "Mentorship e Programs" in text  # conjunção em português
    assert "Tente perguntar sobre um desses temas." in text


def test_english_copy_uses_english_conjunction():
    text = build_out_of_scope_reply(SECOES, "what is the renewal process?")
    assert text.startswith("I didn't find information about this in the knowledge base.")
    assert "Mentorship and Programs" in text


def test_section_titles_are_stripped():
    text = build_out_of_scope_reply(["Conferences ", " Programs"], "o que é isso?")
    assert "Conferences e Programs" in text
    assert "Conferences  e" not in text


def test_single_section_has_no_conjunction():
    text = build_out_of_scope_reply(["Programs"], "o que é isso?")
    assert "sobre os produtos e programas do ecossistema — Programs." in text


def test_empty_sections_degrades_gracefully():
    text = build_out_of_scope_reply([], "o que é isso?")
    assert text.startswith("Não encontrei informações sobre isso na base de conhecimento.")
    assert "—" not in text  # sem lista vazia pendurada
