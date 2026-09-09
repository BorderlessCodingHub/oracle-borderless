"""Modelo de dados do harness de eval (offline). Puro: sem pydantic_ai, sem I/O
além do load de casos. Ver docs/superpowers/specs/2026-07-22-judge-eval-design.md."""

import json
from dataclasses import dataclass, field
from pathlib import Path

FAITHFULNESS = "faithfulness"
CITATION_SUPPORT = "citation_support"
APPROPRIATE_REFUSAL = "appropriate_refusal"
# Métrica determinística: o destino resolvido pelo turno bate (ou não) com o
# esperado. Não passa pelo juiz — não há o que interpretar num id.
NAVIGATION_TARGET = "navigation_target"

CATEGORIES = ("answerable", "refusal", "multi_turn", "adversarial", "navigation")

_METRICS_BY_CATEGORY = {
    "answerable": (FAITHFULNESS, CITATION_SUPPORT),
    "multi_turn": (FAITHFULNESS, CITATION_SUPPORT),
    "refusal": (APPROPRIATE_REFUSAL,),
    "adversarial": (FAITHFULNESS,),
    "navigation": (NAVIGATION_TARGET,),
}


def metrics_for_category(category: str) -> tuple[str, ...]:
    return _METRICS_BY_CATEGORY[category]


@dataclass
class Turn:
    role: str
    content: str


@dataclass
class EvalCase:
    id: str
    category: str
    question: str
    history: list[Turn] = field(default_factory=list)
    should_refuse: bool = False
    poisoned_context: str | None = None
    notes: str | None = None
    # Categoria `navigation`: o id do destino que o turno deve resolver.
    # `None` é uma afirmação, não uma omissão — o turno NÃO pode navegar
    # (pergunta ambígua demais para escolher um destino).
    expected_destination: str | None = None
    # "navigate" (barra de navegação da plataforma) ou "chat"; None = "chat".
    mode: str | None = None
    locale: str | None = None


@dataclass
class MetricScore:
    score: float
    reason: str


@dataclass
class CaseResult:
    case_id: str
    category: str
    answer: str
    scores: dict[str, MetricScore]


def load_cases(path) -> list[EvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for i, obj in enumerate(raw):
        cid = obj.get("id")
        if not cid:
            raise ValueError(f"case #{i} missing 'id'")
        if cid in seen:
            raise ValueError(f"duplicate case id: {cid}")
        seen.add(cid)
        category = obj.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"case {cid}: unknown category {category!r}")
        if not obj.get("question"):
            raise ValueError(f"case {cid}: missing 'question'")
        if category == "adversarial" and not obj.get("poisoned_context"):
            raise ValueError(f"case {cid}: adversarial requires 'poisoned_context'")
        if category == "refusal" and not obj.get("should_refuse", False):
            raise ValueError(f"case {cid}: refusal requires should_refuse=true")
        # A CHAVE precisa existir; o valor pode ser null (caso ambíguo). Sem
        # isto, esquecer o destino esperado viraria silenciosamente "não navegue".
        if category == "navigation" and "expected_destination" not in obj:
            raise ValueError(f"case {cid}: navigation requires 'expected_destination' (may be null)")
        history = [Turn(t["role"], t["content"]) for t in obj.get("history", [])]
        cases.append(
            EvalCase(
                id=cid,
                category=category,
                question=obj["question"],
                history=history,
                should_refuse=obj.get("should_refuse", False),
                poisoned_context=obj.get("poisoned_context"),
                notes=obj.get("notes"),
                expected_destination=obj.get("expected_destination"),
                mode=obj.get("mode"),
                locale=obj.get("locale"),
            )
        )
    return cases
