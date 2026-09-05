"""Body do POST /conversations/ask: o `RunAgentInput` do AG-UI (ADR-0019).

Regra 7 do CLAUDE.md: schema Pydantic mora em src/app/api/. O protocolo entra
aqui e no encoder de src/app/api/streaming/ — nunca em domain/ ou support/agent/.

O que é nosso por cima do protocolo:
- `threadId` é o id da conversa e `runId` é o run do LangSmith: ambos UUID.
- A pergunta é a ÚLTIMA mensagem, que precisa ser do usuário e ter texto. O
  resto do histórico do cliente é ignorado — a recência vem do Postgres.
- `tools`, `context`, `state`, `forwardedProps`, `resume`: aceitos e ignorados.
"""

from uuid import UUID

from ag_ui.core import RunAgentInput, UserMessage
from pydantic import model_validator


def _require_uuid(value: str, field: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} deve ser um UUID") from exc


def _text_of(message: UserMessage) -> str:
    content = message.content
    if not isinstance(content, str):
        raise ValueError("a última mensagem deve ser texto puro")
    return content.strip()


class RunAgentRequest(RunAgentInput):
    @model_validator(mode="after")
    def _oracle_rules(self):
        _require_uuid(self.thread_id, "threadId")
        _require_uuid(self.run_id, "runId")
        if not self.messages:
            raise ValueError("messages não pode ser vazio")
        last = self.messages[-1]
        if not isinstance(last, UserMessage) or last.role != "user":
            raise ValueError("a última mensagem deve ser do usuário (role=user)")
        if not _text_of(last):
            raise ValueError("a última mensagem não pode ser vazia")
        return self

    @property
    def question(self) -> str:
        return _text_of(self.messages[-1])

    @property
    def conversation_id(self) -> UUID:
        return UUID(self.thread_id)
