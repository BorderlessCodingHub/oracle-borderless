"""Body do POST /conversations/ask (ADR-0021): os parâmetros de
`astream_events(input, config)`.

Regra 7 do CLAUDE.md: schema Pydantic mora em src/app/api/. Só seis campos são
nossos — `input.question`, `input.mode` ("chat", "navigate" ou "mentor"),
`input.locale`, `input.lesson_id` (só mode="mentor"), `config.run_id` (run do
LangSmith) e `config.configurable.thread_id` (id da conversa). Qualquer outra
chave é aceita e ignorada: o servidor monta o `config` real do grafo; o
cliente não injeta `configurable`.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


def _canonical_uuid(value: str, field: str) -> str:
    """Valida e devolve a forma canônica (minúscula, com hífens) — sem isso, um
    UUID válido mas escrito diferente fluiria sem normalização até o run_id do
    LangSmith e o agent_traces.langsmith_run_id."""
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} deve ser um UUID") from exc


class StreamInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    mode: Literal["chat", "navigate", "mentor"] = "chat"
    locale: Literal["en", "pt-BR"] = "pt-BR"
    # Só o modo mentor usa: id do vídeo na Platform. O escopo da busca sai
    # daqui, não do modelo (spec §2.1).
    lesson_id: str | None = None

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a pergunta não pode ser vazia")
        return value


class StreamConfigurable(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thread_id: str

    @field_validator("thread_id")
    @classmethod
    def _uuid(cls, value: str) -> str:
        return _canonical_uuid(value, "thread_id")


class StreamConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    configurable: StreamConfigurable

    @field_validator("run_id")
    @classmethod
    def _uuid(cls, value: str) -> str:
        return _canonical_uuid(value, "run_id")


class StreamEventsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input: StreamInput
    config: StreamConfig

    @property
    def question(self) -> str:
        return self.input.question

    @property
    def mode(self) -> str:
        return self.input.mode

    @property
    def locale(self) -> str:
        return self.input.locale

    @property
    def lesson_id(self) -> str | None:
        return self.input.lesson_id

    @property
    def conversation_id(self) -> UUID:
        return UUID(self.config.configurable.thread_id)

    @property
    def run_id(self) -> str:
        return self.config.run_id
