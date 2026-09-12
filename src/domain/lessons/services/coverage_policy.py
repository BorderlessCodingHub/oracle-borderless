"""Rótulo de cobertura de uma pergunta. Puro, sem I/O.

Os limiares NÃO bloqueiam nada: o mentor já respondeu quando isto roda. Eles
existem para separar, no `agent_traces`, a pergunta que a aula cobriu da que
virou backlog de conteúdo (spec §9.2). A distância bruta também é gravada, para
que recalibrar os limiares seja um UPDATE no histórico, não perder o passado.
"""

from src.support.core.settings import settings

COVERED = "covered"
PARTIAL = "partial"
GAP = "gap"


def classify_coverage(best_distance: float | None) -> str:
    if best_distance is None:
        return GAP
    if best_distance <= settings.MENTOR_COVERAGE_NEAR:
        return COVERED
    if best_distance <= settings.MENTOR_COVERAGE_FAR:
        return PARTIAL
    return GAP
