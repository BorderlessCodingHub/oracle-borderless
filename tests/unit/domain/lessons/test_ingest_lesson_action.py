from pathlib import Path
from uuid import uuid4

import pytest

from src.domain.lessons.actions.ingest_lesson_action import IngestLessonAction
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.transcript_segment import TranscriptSegment
from src.domain.lessons.enums import TranscriptStatus


class FakeLessonRepo:
    def __init__(self) -> None:
        self.saved: list[Lesson] = []

    async def save(self, lesson: Lesson) -> Lesson:
        self.saved.append(
            Lesson(**{**lesson.__dict__})  # snapshot, não referência viva
        )
        return lesson


class FakeChunkRepo:
    def __init__(self) -> None:
        self.replaced: list[tuple] = []

    async def replace_for_lesson(self, lesson_id, chunks) -> None:
        self.replaced.append((lesson_id, list(chunks)))


class FakeEmbeddings:
    async def embed(self, texts):
        return [[float(i)] * 3 for i, _ in enumerate(texts)]


class FakeClient:
    def __init__(self, url="https://cdn.test/a.m3u8"):
        self.url = url

    async def get_media(self, video_id):
        from src.support.clients.borderless.borderless_lessons_client import LessonMedia

        return LessonMedia(url=self.url, expires_at=None, content_type=None)


class FakeTranscription:
    def __init__(self, segments):
        self._segments = segments

    async def transcribe(self, audio_path: Path, prompt: str):
        return list(self._segments)


def a_lesson(**overrides) -> Lesson:
    base = dict(
        uuid=uuid4(), platform_video_id="v1", program_slug="base",
        module_slug="m1", video_slug="a1", title="Tokens",
        provider="PANDA_VIDEO", provider_ref="ref-1",
    )
    base.update(overrides)
    return Lesson(**base)


def build_action(monkeypatch, segments=None, lesson_repo=None, chunk_repo=None, transcription=None):
    """Neutraliza o ffmpeg: a Task 5 já cobre o toolkit, aqui interessa o fluxo."""
    from src.domain.lessons.actions import ingest_lesson_action as module

    async def fake_extract(source_url, dest):
        Path(dest).write_bytes(b"audio")

    async def fake_probe(path):
        return 100.0

    async def fake_slice(path, start, length, dest):
        Path(dest).write_bytes(b"audio")

    monkeypatch.setattr(module.AudioToolkit, "extract_audio", staticmethod(fake_extract))
    monkeypatch.setattr(module.AudioToolkit, "probe_duration", staticmethod(fake_probe))
    monkeypatch.setattr(module.AudioToolkit, "slice", staticmethod(fake_slice))

    return IngestLessonAction(
        embeddings=FakeEmbeddings(),
        lessons_client=FakeClient(),
        transcription=transcription or FakeTranscription(segments or []),
        lesson_repo=lesson_repo or FakeLessonRepo(),
        chunk_repo=chunk_repo or FakeChunkRepo(),
    )


@pytest.mark.asyncio
async def test_happy_path_reaches_ready_and_writes_chunks(monkeypatch):
    lesson_repo, chunk_repo = FakeLessonRepo(), FakeChunkRepo()
    action = build_action(
        monkeypatch,
        segments=[TranscriptSegment("olá pessoal", 0.0, 2.0), TranscriptSegment("tokens", 2.0, 4.0)],
        lesson_repo=lesson_repo, chunk_repo=chunk_repo,
    )

    result = await action.execute(a_lesson())

    assert result.status == TranscriptStatus.READY
    assert result.chunks == 1
    assert chunk_repo.replaced[0][1][0].start_seconds == 0.0
    assert chunk_repo.replaced[0][1][0].end_seconds == 4.0
    # claim antes do trabalho, ready depois
    assert lesson_repo.saved[0].transcript_status == TranscriptStatus.TRANSCRIBING
    assert lesson_repo.saved[0].attempts == 1
    assert lesson_repo.saved[-1].transcript_status == TranscriptStatus.READY
    assert lesson_repo.saved[-1].failure_reason is None


@pytest.mark.asyncio
async def test_same_hash_skips_the_expensive_half(monkeypatch):
    segments = [TranscriptSegment("mesmo texto", 0.0, 1.0)]
    chunk_repo = FakeChunkRepo()
    action = build_action(monkeypatch, segments=segments, chunk_repo=chunk_repo)

    first = await action.execute(a_lesson())
    second = await action.execute(
        a_lesson(content_hash=first.content_hash, transcript_status=TranscriptStatus.READY)
    )

    assert second.skipped is True
    assert second.status == TranscriptStatus.READY
    assert len(chunk_repo.replaced) == 1  # não re-embedou


@pytest.mark.asyncio
async def test_force_re_embeds_even_with_the_same_hash(monkeypatch):
    segments = [TranscriptSegment("mesmo texto", 0.0, 1.0)]
    chunk_repo = FakeChunkRepo()
    action = build_action(monkeypatch, segments=segments, chunk_repo=chunk_repo)

    first = await action.execute(a_lesson())
    await action.execute(
        a_lesson(content_hash=first.content_hash, transcript_status=TranscriptStatus.READY),
        force=True,
    )

    assert len(chunk_repo.replaced) == 2


@pytest.mark.asyncio
async def test_transcription_failure_marks_failed_and_does_not_raise(monkeypatch):
    class Boom:
        async def transcribe(self, audio_path, prompt):
            raise RuntimeError("provider 503")

    lesson_repo = FakeLessonRepo()
    action = build_action(monkeypatch, transcription=Boom(), lesson_repo=lesson_repo)

    result = await action.execute(a_lesson())

    assert result.status == TranscriptStatus.FAILED
    assert "provider 503" in result.failure_reason
    assert lesson_repo.saved[-1].transcript_status == TranscriptStatus.FAILED
    assert lesson_repo.saved[-1].attempts == 1


@pytest.mark.asyncio
async def test_empty_transcript_is_a_failure_not_a_silent_success(monkeypatch):
    action = build_action(monkeypatch, segments=[])
    result = await action.execute(a_lesson())
    assert result.status == TranscriptStatus.FAILED
    assert "vazia" in result.failure_reason.lower()


@pytest.mark.asyncio
async def test_the_glossary_prompt_carries_the_lesson_title(monkeypatch):
    seen: list[str] = []

    class Spy:
        async def transcribe(self, audio_path, prompt):
            seen.append(prompt)
            return [TranscriptSegment("x", 0.0, 1.0)]

    action = build_action(monkeypatch, transcription=Spy())
    await action.execute(a_lesson(title="Tokens e embeddings"))

    assert "Tokens e embeddings" in seen[0]
