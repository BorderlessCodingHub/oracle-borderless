"""Speech-to-text com timestamps por segmento.

`whisper-1` com `response_format="verbose_json"` devolve `segments` com `start`
e `end` — é o que sustenta a citação "por volta de 12:30" (spec §7). Modelos de
transcrição mais novos têm qualidade melhor mas formato de saída diferente;
antes de trocar `MENTOR_TRANSCRIBE_MODEL`, confirme que o retorno traz segmentos
equivalentes, senão a citação temporal morre silenciosamente.
"""

import logging
from pathlib import Path

from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


class TranscriptionClient:
    def __init__(self, openai_client=None) -> None:
        if openai_client is None:
            from openai import AsyncOpenAI

            openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._client = openai_client
        self._model = settings.MENTOR_TRANSCRIBE_MODEL
        self._language = settings.MENTOR_TRANSCRIBE_LANGUAGE

    async def transcribe(self, audio_path: Path, prompt: str) -> list[TranscriptSegment]:
        with audio_path.open("rb") as handle:
            response = await self._client.audio.transcriptions.create(
                model=self._model,
                file=handle,
                language=self._language,
                # Glossário: segura "embedding", "autorregressão", "tokenização".
                prompt=prompt,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        raw = getattr(response, "segments", None) or []
        return [
            TranscriptSegment(
                text=str(getattr(s, "text", "")).strip(),
                start=float(getattr(s, "start", 0.0)),
                end=float(getattr(s, "end", 0.0)),
            )
            for s in raw
        ]
