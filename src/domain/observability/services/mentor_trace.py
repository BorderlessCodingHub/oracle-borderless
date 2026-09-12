"""Preenche o draft do trace com os sinais do turno mentor (Task 5).

Puro, sem I/O: recebe o `configurable` do turno (o mesmo dict que a tool
`search_lesson` — Task 2 — estende/preenche em place) e escreve no draft. Vive
fora do controller para que o preenchimento seja testável sem sessão/HTTP; o
call site real continua sob o `try/except` do ADR-0013, que loga e engole.
"""

from src.domain.lessons.services.coverage_policy import classify_coverage
from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft


def apply_mentor_signals(draft: TurnTraceDraft, cfg: dict) -> None:
    """`lesson_distances` nasce vazia e é estendida pela tool; `question_embedding`
    idem, mas chega como lista vazia quando a tool nunca rodou — vira `None`
    para não confundir "sem pergunta embedada" com "embedding zero" (C5).
    """
    distances = cfg.get("lesson_distances") or []
    embedding = cfg.get("question_embedding") or None
    best = min(distances) if distances else None

    draft.intent = "mentor"
    draft.lesson_id = cfg.get("lesson_platform_video_id")
    draft.program_slug = cfg.get("lesson_program_slug")
    draft.retrieval_ran = bool(distances)
    draft.retrieval_kept = len(distances)
    draft.retrieval_best_distance = best
    draft.lesson_coverage = classify_coverage(best)
    # Já foi calculado para fazer a busca: descartá-lo obrigaria a re-embedar
    # o backlog inteiro quando formos agrupar as perguntas.
    draft.question_embedding = embedding
