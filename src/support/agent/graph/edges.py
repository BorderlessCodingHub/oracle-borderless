"""As três decisões do turno. Funções puras: recebem estado, devolvem o nome do
próximo nó. Tradução 1:1 do if/else que vivia em AnswerQuestionAction."""

from typing import Literal

from src.support.agent.graph.state import TurnState


def route_entry(state: TurnState) -> Literal["answer", "gate"]:
    """Knowledge pré-semeado pula gate e retrieval.

    Existe para o harness de eval: nos casos `adversarial` o contexto envenenado
    é injetado à mão, e fazer o gate classificá-lo mediria a coisa errada.
    """
    return "answer" if state.get("preset_knowledge") else "gate"


def should_retrieve(state: TurnState) -> Literal["retrieve", "answer"]:
    return "retrieve" if state.get("retrieve") else "answer"


def has_grounding(state: TurnState) -> Literal["refuse", "answer"]:
    """Recusa só quando o gate PEDIU busca de verdade e nada passou do limiar.

    Um gate `degraded` (erro/timeout) nunca classificou o turno: o retrieve=True
    dali é o chute de segurança do fail-open, não uma decisão fundamentada.
    Recusar nesse caso seria injustificado (ex.: "oi" durante um timeout).
    """
    if state.get("knowledge"):
        return "answer"
    return "answer" if state.get("degraded") else "refuse"
