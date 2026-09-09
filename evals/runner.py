"""Runner do harness de eval: monta o pipeline REAL por caso (grafo LangGraph),
coleta a resposta e as fontes usadas, e chama o juiz. NÃO persiste nada
(não persiste nada: sem Actions de conversa, sem escrita em conversations/messages)."""

import logging

from evals.models import NAVIGATION_TARGET, CaseResult, EvalCase, MetricScore, metrics_for_category
from src.domain.conversations.services.out_of_scope_reply import (
    OUT_OF_SCOPE_OPENING_PT,
    build_out_of_scope_reply,
)
from src.domain.documents.actions.list_knowledge_sections_action import ListKnowledgeSectionsAction
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import (
    AgentMessage,
    KnowledgeSnippet,
    TurnDependencies,
    TurnSignals,
    navigation_of,
    text_of,
)

logger = logging.getLogger(__name__)


def _sources_text(knowledge: list[KnowledgeSnippet]) -> str:
    if not knowledge:
        return "(nenhuma fonte recuperada)"
    return "\n\n".join(f"[{s.citation.title}] {s.content}" for s in knowledge)


async def _collect(run) -> tuple[str, dict | None]:
    """As duas fases, na ordem. O harness inteiro já roda dentro de um escopo de
    sessão (evals/__main__.py), então não há troca de escopo entre elas aqui.
    `text_of` lê tokens do `answer` e o texto canônico da recusa (ADR-0021);
    `navigation_of` lê o destino resolvido (chunk `updates` do nó `navigate` e,
    repetido, o `on_chain_end` do raiz) — o último visto vence."""
    text = ""
    navigation = None
    async for event in run.prelude():
        text += text_of(event)
        navigation = navigation_of(event) or navigation
    async for event in run.stream():
        text += text_of(event)
        navigation = navigation_of(event) or navigation
    return text, navigation


def _refused(case: EvalCase, answer: str) -> bool:
    """A abertura canônica da RESPOSTA PADRÃO no idioma do caso. `OUT_OF_SCOPE_OPENING_PT`
    é a que está no system prompt; a versão em inglês não é exportada, então ela
    vem da própria função que a plataforma usa (primeira linha da recusa)."""
    opening = build_out_of_scope_reply([], case.question).split("\n", 1)[0]
    return OUT_OF_SCOPE_OPENING_PT in answer or opening in answer


def _score_navigation(case: EvalCase, answer: str, navigation: dict | None) -> dict[str, MetricScore]:
    """Determinística: nada de juiz. Um id ou bate ou não bate — e uma recusa
    padrão zera o caso mesmo com o destino certo (o turno de navegação nunca
    deve recusar; ver bloco NAVEGAÇÃO do prompt)."""
    got = ((navigation or {}).get("destination") or {}).get("id")
    if _refused(case, answer):
        return {NAVIGATION_TARGET: MetricScore(0.0, f"recusa padrão na resposta (destino={got!r})")}
    if case.expected_destination is None:
        if navigation is None:
            return {NAVIGATION_TARGET: MetricScore(1.0, "não navegou, como esperado")}
        return {NAVIGATION_TARGET: MetricScore(0.0, f"navegou para {got!r} sendo que não devia navegar")}
    if got == case.expected_destination:
        return {NAVIGATION_TARGET: MetricScore(1.0, f"destino {got!r} como esperado")}
    return {NAVIGATION_TARGET: MetricScore(0.0, f"esperado {case.expected_destination!r}, obtido {got!r}")}


async def run_case(case: EvalCase, *, graph, search, judge, extra_config: dict | None = None) -> CaseResult:
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
    run = graph.run(
        case.question, history, deps, signals, knowledge=knowledge,
        mode=case.mode or "chat", locale=case.locale or "pt-BR", extra_config=extra_config,
    )
    answer, navigation = await _collect(run)

    if case.category == "navigation":
        # Sem juiz e sem refazer a busca: a métrica olha só o destino resolvido.
        scores = _score_navigation(case, answer, navigation)
        return CaseResult(case_id=case.id, category=case.category, answer=answer, scores=scores)

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


async def run_all(
    cases: list[EvalCase], *, graph, search, judge, extra_config: dict | None = None
) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        results.append(
            await run_case(case, graph=graph, search=search, judge=judge, extra_config=extra_config)
        )
    return results
