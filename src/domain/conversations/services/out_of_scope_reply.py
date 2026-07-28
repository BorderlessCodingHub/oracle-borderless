"""Resposta padrão quando a pergunta não está coberta pela base.

Função pura: recebe os temas já resolvidos e a pergunta, devolve o texto. Sem
I/O e sem LLM — a recusa é instantânea e a cópia é exatamente esta.
"""

import re

# Marcadores disjuntos: nenhuma palavra aparece nos dois conjuntos, senão a
# contagem empata à toa. "a" ficou fora por ser artigo nos dois idiomas.
_PT_MARKERS = frozenset(
    {
        "o", "os", "as", "de", "da", "do", "que", "qual", "quais", "como",
        "por", "para", "não", "é", "um", "uma", "quem", "onde", "quando", "sobre",
    }
)
_EN_MARKERS = frozenset(
    {
        "the", "an", "of", "what", "which", "how", "why", "for", "is", "are",
        "does", "who", "where", "when", "can", "about",
    }
)

_WORD_RE = re.compile(r"[a-zà-ÿ]+")

OUT_OF_SCOPE_OPENING_PT = "Não encontrei informações sobre isso na base de conhecimento."
_OPENING_EN = "I didn't find information about this in the knowledge base."

_BODY_PT = "Eu respondo sobre os produtos e programas do ecossistema — {temas}."
_BODY_EN = "I answer questions about the ecosystem's products and programs — {temas}."
_BODY_PT_EMPTY = "Eu respondo sobre os produtos e programas do ecossistema."
_BODY_EN_EMPTY = "I answer questions about the ecosystem's products and programs."

_CLOSING_PT = "Tente perguntar sobre um desses temas."
_CLOSING_EN = "Try asking about one of those topics."


def detect_language(text: str) -> str:
    """`"en"` só quando o inglês tem mais marcadores; pt-BR é o default."""
    words = _WORD_RE.findall(text.lower())
    pt = sum(1 for w in words if w in _PT_MARKERS)
    en = sum(1 for w in words if w in _EN_MARKERS)
    return "en" if en > pt else "pt"


def _join(items: list[str], conjunction: str) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"


def build_out_of_scope_reply(sections: list[str], question: str) -> str:
    cleaned = [s.strip() for s in sections if s and s.strip()]
    english = detect_language(question) == "en"

    opening = _OPENING_EN if english else OUT_OF_SCOPE_OPENING_PT
    closing = _CLOSING_EN if english else _CLOSING_PT
    if cleaned:
        temas = _join(cleaned, "and" if english else "e")
        body = (_BODY_EN if english else _BODY_PT).format(temas=temas)
    else:
        body = _BODY_EN_EMPTY if english else _BODY_PT_EMPTY

    return f"{opening}\n\n{body} {closing}"
