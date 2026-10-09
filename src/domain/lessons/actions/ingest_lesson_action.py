"""Ingestão de UMA aula: claim → mídia → áudio → fatias → transcrição → hash →
chunks → embeddings → ready.

Cada aula falha sozinha. O `execute` não propaga exceção: ele grava
`failure_reason`, marca `FAILED` e devolve o resultado, para que um lote de 30
aulas não morra por causa de uma (spec §7).

O claim (`TRANSCRIBING` + `attempts += 1`) leva um commit imediato — spec §7
passo 1 — logo após o `save()`, e não só no fim do `execute`: sem isso a marca
nunca sai da transação aberta, nenhuma execução concorrente a enxerga, e a
recuperação de claim obsoleto em `list_pending` fica sem o que recuperar.
"""

import hashlib
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from uuid6 import uuid7

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_chunk_repository import LessonChunkRepository
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.domain.lessons.services.transcript_chunking_service import TranscriptChunkingService
from src.support.clients.transcription.audio_toolkit import AudioToolkit
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    platform_video_id: str
    status: TranscriptStatus
    chunks: int
    skipped: bool
    failure_reason: str | None
    content_hash: str | None


class IngestLessonAction:
    def __init__(
        self,
        embeddings,
        lessons_client,
        transcription,
        lesson_repo=None,
        chunk_repo=None,
    ) -> None:
        self.embeddings = embeddings
        self.lessons_client = lessons_client
        self.transcription = transcription
        self.lessons = lesson_repo or LessonRepository()
        self.chunks = chunk_repo or LessonChunkRepository()
        self.chunking = TranscriptChunkingService()

    async def execute(self, lesson: Lesson, force: bool = False) -> IngestResult:
        try:
            lesson.transcript_status = TranscriptStatus.TRANSCRIBING
            lesson.attempts += 1
            lesson.failure_reason = None
            await self.lessons.save(lesson)
            # Commit imediato do claim — spec §7 passo 1: sem isso, o
            # `save()` só dá flush, a marca `transcribing` nunca sai da
            # transação aberta e nenhuma execução concorrente a enxerga —
            # duas execuções processariam a mesma aula ao mesmo tempo e a
            # recuperação de claim obsoleto em `list_pending` nunca teria uma
            # linha `transcribing` committed para recuperar.
            await CurrentAsyncSessionContext.get().commit()
        except Exception as exc:
            # O claim em si não commitou: não há nada seguro para persistir
            # aqui (se o banco está fora do ar, tentar salvar FAILED só
            # repetiria a mesma falha) — o resultado FAILED em memória é o
            # que garante que o lote continue sem propagar a exceção.
            logger.exception("falha ao registrar o claim da aula %s", lesson.platform_video_id)
            reason = f"claim falhou: {type(exc).__name__}: {exc}"[:1000]
            return IngestResult(
                lesson.platform_video_id, TranscriptStatus.FAILED,
                chunks=0, skipped=False, failure_reason=reason, content_hash=lesson.content_hash,
            )

        try:
            segments = await self._transcribe(lesson)
            if not segments:
                raise ValueError("transcrição vazia — nenhum segmento de fala")

            text = " ".join(s.text for s in segments)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

            if digest == lesson.content_hash and not force:
                lesson.transcript_status = TranscriptStatus.READY
                await self.lessons.save(lesson)
                return IngestResult(
                    lesson.platform_video_id, TranscriptStatus.READY,
                    chunks=0, skipped=True, failure_reason=None, content_hash=digest,
                )

            written = await self._embed_and_store(lesson, segments)

            lesson.transcript_text = text
            lesson.content_hash = digest
            lesson.transcript_status = TranscriptStatus.READY
            lesson.transcribed_at = datetime.now(timezone.utc)
            lesson.failure_reason = None
            await self.lessons.save(lesson)

            return IngestResult(
                lesson.platform_video_id, TranscriptStatus.READY,
                chunks=written, skipped=False, failure_reason=None, content_hash=digest,
            )

        except Exception as exc:  # uma aula ruim não derruba o lote
            logger.exception("falha ao ingerir a aula %s", lesson.platform_video_id)
            reason = f"{type(exc).__name__}: {exc}"[:1000]
            lesson.transcript_status = TranscriptStatus.FAILED
            lesson.failure_reason = reason
            try:
                await self.lessons.save(lesson)
            except Exception:
                # Se nem o registro da falha for salvo (ex.: banco fora do ar),
                # ainda assim o `execute` não pode propagar — o resultado FAILED
                # com o motivo ORIGINAL é o que garante que o lote continue.
                logger.exception(
                    "falha ao salvar o status FAILED da aula %s", lesson.platform_video_id
                )
            return IngestResult(
                lesson.platform_video_id, TranscriptStatus.FAILED,
                chunks=0, skipped=False, failure_reason=reason, content_hash=lesson.content_hash,
            )

    async def _transcribe(self, lesson: Lesson) -> list[TranscriptSegment]:
        media = await self.lessons_client.get_media(lesson.platform_video_id)
        prompt = self._glossary(lesson)

        with tempfile.TemporaryDirectory(prefix="mentor-") as workdir:
            root = Path(workdir)
            audio = root / "full.mp3"
            await AudioToolkit.extract_audio(media.url, audio)
            duration = await AudioToolkit.probe_duration(audio)

            windows = AudioToolkit.plan_segments(duration, settings.MENTOR_AUDIO_SEGMENT_SECONDS)
            segments: list[TranscriptSegment] = []
            for index, (start, length) in enumerate(windows):
                part = root / f"part-{index}.mp3"
                await AudioToolkit.slice(audio, start, length, part)
                # O modelo só enxerga a fatia, então os tempos voltam zerados:
                # o offset da fatia é somado aqui, não lá.
                segments.extend(s.shifted(start) for s in await self.transcription.transcribe(part, prompt))
            return segments

    @staticmethod
    def _glossary(lesson: Lesson) -> str:
        """Prompt de transcrição: segura os termos técnicos que o modelo erraria
        em português falado (spec §7)."""
        return (
            f"Aula do programa Borderless: {lesson.title}. "
            "Termos técnicos frequentes: embedding, embeddings, tokenização, "
            "autorregressão, autorregressivo, vetor, similaridade, prompt, "
            "LLM, API, deploy, backend, frontend."
        )

    async def _embed_and_store(self, lesson: Lesson, segments: list[TranscriptSegment]) -> int:
        pieces = self.chunking.split(segments)
        vectors = await self.embeddings.embed([text for text, _, _ in pieces])
        entities = [
            LessonChunk(
                uuid=uuid7(),
                lesson_id=lesson.uuid,
                ordinal=i,
                content=text,
                start_seconds=start,
                end_seconds=end,
                embedding=vectors[i],
            )
            for i, (text, start, end) in enumerate(pieces)
        ]
        await self.chunks.replace_for_lesson(lesson.uuid, entities)
        return len(entities)
