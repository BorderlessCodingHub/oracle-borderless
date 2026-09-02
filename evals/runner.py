"""Runner do harness de eval: monta o pipeline REAL por caso (grafo LangGraph),
coleta a resposta e as fontes usadas, e chama o juiz. NÃO persiste nada
(sem AnswerQuestionAction, sem escrita em conversations/messages)."""

import logging

from evals.models import CaseResult, EvalCase, MetricScore, metrics_for_category
from src.domain.conversations.services.out_of_scope_reply import build_out_of_scope_reply
from src.domain.documents.actions.list_knowledge_sections_action import ListKnowledgeSectionsAction
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import AgentMessage, KnowledgeSnippet, TurnDependencies, TurnSignals

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


async def run_case(case: EvalCase, *, graph, search, judge) -> CaseResult:
    history = [AgentMessage(role=t.role, content=t.content) for t in case.history]

    # Casos adversariais injetam o contexto envenenado à mão: fazer o gate
    # classificá-lo mediria a coisa errada. `knowledge` pré-semeado faz o grafo
    # entrar direto no nó de resposta (aresta route_entry).
    knowledge = None
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

    signals = TurnSignals()
    deps = TurnDependencies(
        search=search,
        sections=ListKnowledgeSectionsAction(),
        refusal=build_out_of_scope_reply,
        nearest=None,
    )
    stream = await graph.start(case.question, history, deps, signals, knowledge=knowledge)
    answer = await _collect_text(stream)

    sources = knowledge if knowledge is not None else []
    if knowledge is None and signals.retrieval_ran:
        # O grafo recuperou internamente; o juiz precisa ver as MESMAS fontes.
        sources = await search.execute(signals.gate_search_query or case.question)

    try:
        scores = await judge.score(case, _sources_text(sources), answer)
    except Exception as exc:  # fail-safe: um caso não-pontuável NÃO pode passar
        logger.warning("juiz falhou no caso %s: %s", case.id, exc)
        scores = {m: MetricScore(0.0, f"judge error: {exc}") for m in metrics_for_category(case.category)}

    return CaseResult(case_id=case.id, category=case.category, answer=answer, scores=scores)


async def run_all(cases: list[EvalCase], *, graph, search, judge) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        results.append(await run_case(case, graph=graph, search=search, judge=judge))
    return results
