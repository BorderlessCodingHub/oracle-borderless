from datetime import datetime, timezone
from uuid import uuid4

from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.mappers.lesson_chunk_mapper import LessonChunkMapper
from src.domain.lessons.mappers.lesson_mapper import LessonMapper
from src.domain.lessons.models.lesson import LessonModel
from src.domain.lessons.models.lesson_chunk import LessonChunkModel


def _lesson(**overrides) -> Lesson:
    base = dict(
        uuid=uuid4(),
        platform_video_id="v1",
        program_slug="base",
        module_slug="modulo-1",
        video_slug="aula-1",
        title="Tokens e embeddings",
        duration_seconds=3600,
        provider="PANDA_VIDEO",
        provider_ref="ref-1",
        transcript_text="oi",
        transcript_status=TranscriptStatus.READY,
        content_hash="abc",
        transcribed_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        attempts=1,
        failure_reason=None,
    )
    base.update(overrides)
    return Lesson(**base)


def test_lesson_round_trip_preserves_every_field():
    entity = _lesson()
    model = LessonModel(**LessonMapper.to_model_attrs(entity))
    assert LessonMapper.to_entity(model) == entity


def test_lesson_status_crosses_as_a_plain_string():
    attrs = LessonMapper.to_model_attrs(_lesson())
    assert attrs["transcript_status"] == "ready"
    assert isinstance(attrs["transcript_status"], str)


def test_chunk_round_trip_preserves_timestamps_and_vector():
    entity = LessonChunk(
        uuid=uuid4(),
        lesson_id=uuid4(),
        ordinal=3,
        content="sobre autorregressão",
        start_seconds=750.5,
        end_seconds=812.25,
        embedding=[0.1, 0.2, 0.3],
    )
    model = LessonChunkModel(**LessonChunkMapper.to_model_attrs(entity))
    assert LessonChunkMapper.to_entity(model) == entity


def test_chunk_without_embedding_maps_to_none():
    entity = LessonChunk(
        uuid=uuid4(), lesson_id=uuid4(), ordinal=0,
        content="x", start_seconds=0.0, end_seconds=1.0, embedding=None,
    )
    model = LessonChunkModel(**LessonChunkMapper.to_model_attrs(entity))
    assert LessonChunkMapper.to_entity(model).embedding is None
