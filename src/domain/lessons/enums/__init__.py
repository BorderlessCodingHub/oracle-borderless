from enum import StrEnum


class TranscriptStatus(StrEnum):
    """Ciclo de vida da transcrição de uma aula.

    `TRANSCRIBING` é o claim: existe para que duas execuções concorrentes do
    comando não transcrevam a mesma aula duas vezes.
    """

    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    READY = "ready"
    FAILED = "failed"
