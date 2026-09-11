from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.domain.lessons.enums import TranscriptStatus


@dataclass
class Lesson:
    """Uma aula da plataforma e o estado da sua transcrição. Domínio puro."""

    uuid: UUID
    platform_video_id: str
    program_slug: str
    module_slug: str
    video_slug: str
    title: str
    duration_seconds: int | None = None
    provider: str = ""
    provider_ref: str = ""
    transcript_text: str | None = None
    transcript_status: TranscriptStatus = TranscriptStatus.PENDING
    content_hash: str | None = None
    transcribed_at: datetime | None = None
    attempts: int = 0
    failure_reason: str | None = None

    def is_ready(self) -> bool:
        return self.transcript_status == TranscriptStatus.READY

    def can_retry(self, max_attempts: int) -> bool:
        return self.attempts < max_attempts
