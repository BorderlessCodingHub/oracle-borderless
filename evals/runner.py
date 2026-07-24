"""Runner do harness de eval: monta o pipeline REAL por caso (gate -> search ->
engine), coleta a resposta e as fontes usadas, e chama o juiz. NÃO persiste nada
(sem AnswerQuestionAction, sem escrita em conversations/messages)."""

import logging

from evals.models import CaseResult, EvalCase, MetricScore, metrics_for_category
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, KnowledgeSnippet

logger = logging.getLogger(__name__)


def _sources_text(knowledge: list[KnowledgeSnippet]) -> str:
    if not knowledge:
        return "(nenhuma fonte recuperada)"
    return "\n\n".join(f"[{s.citation.title}] {s.content}" for s in knowledge)


async def _collect_text(stream) -> str:
    text = ""
    async for chunk in stream:
        if chunk.type == "text":
            text += chunk.text
    return text


async def run_case(case: EvalCase, *, gate, search, engine, judge) -> CaseResult:
    history = [AgentMessage(role=t.role, content=t.content) for t in case.history]

    if case.category == "adversarial":
        knowledge = [
            KnowledgeSnippet(
                content=case.poisoned_context,
                citation=Citation(
                    source_type="notion",
                    title="(injected)",
                    url="",
                    snippet=case.poisoned_context[:200],
                ),
            )
        ]
    else:
        decision = await gate.decide(case.question, history)
        knowledge = await search.execute(decision.search_query) if decision.retrieve else []

    answer = await _collect_text(engine.stream_answer(case.question, history, knowledge))

    try:
        scores = await judge.score(case, _sources_text(knowledge), answer)
    except Exception as exc:  # fail-safe: um caso não-pontuável NÃO pode passar
        logger.warning("juiz falhou no caso %s: %s", case.id, exc)
        scores = {m: MetricScore(0.0, f"judge error: {exc}") for m in metrics_for_category(case.category)}

    return CaseResult(case_id=case.id, category=case.category, answer=answer, scores=scores)


async def run_all(cases: list[EvalCase], *, gate, search, engine, judge) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        results.append(await run_case(case, gate=gate, search=search, engine=engine, judge=judge))
    return results
