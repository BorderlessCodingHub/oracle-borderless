"""O que OpenTurnAction (escopo 1, request) entrega a RunTurnAction (escopo 2,
corpo SSE). Dataclass pura: cruza a fronteira de sessão sem carregar nada de
banco — só ids, texto, o histórico já carregado e os coletores do trace."""

from dataclasses import dataclass
from uuid import UUID

from src.domain.observability.dtos.turn_trace_draft import TurnTraceDraft
from src.support.agent.ports import AgentMessage, TurnSignals


@dataclass
class OpenedTurn:
    conversation_id: UUID
    question: str
    history: list[AgentMessage]
    draft: TurnTraceDraft
    signals: TurnSignals  # o MESMO objeto pendurado em draft.signals
    mode: str = "chat"
    locale: str = "pt-BR"
    # Só mode="mentor": id do vídeo na Platform (o mesmo que `state["lesson_id"]`
    # recebe — C1: o id INTERNO (lessons.uuid) viaja à parte, em extra_config).
    lesson_id: str | None = None
