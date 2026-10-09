from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.models.lesson import LessonModel


class LessonMapper:
    @staticmethod
    def to_entity(model: LessonModel) -> Lesson:
        return Lesson(
            uuid=model.uuid,
            platform_video_id=model.platform_video_id,
            program_slug=model.program_slug,
            module_slug=model.module_slug,
            video_slug=model.video_slug,
            title=model.title,
            duration_seconds=model.duration_seconds,
            provider=model.provider,
            provider_ref=model.provider_ref,
            transcript_text=model.transcript_text,
            transcript_status=TranscriptStatus(model.transcript_status),
            content_hash=model.content_hash,
            transcribed_at=model.transcribed_at,
            attempts=model.attempts,
            failure_reason=model.failure_reason,
        )

    @staticmethod
    def to_model_attrs(entity: Lesson) -> dict:
        return {
            "uuid": entity.uuid,
            "platform_video_id": entity.platform_video_id,
            "program_slug": entity.program_slug,
            "module_slug": entity.module_slug,
            "video_slug": entity.video_slug,
            "title": entity.title,
            "duration_seconds": entity.duration_seconds,
            "provider": entity.provider,
            "provider_ref": entity.provider_ref,
            "transcript_text": entity.transcript_text,
            "transcript_status": str(entity.transcript_status),
            "content_hash": entity.content_hash,
            "transcribed_at": entity.transcribed_at,
            "attempts": entity.attempts,
            "failure_reason": entity.failure_reason,
        }
