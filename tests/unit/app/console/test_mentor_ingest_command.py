from uuid import uuid4

from src.app.console.commands.mentor_ingest_command import (
    MentorIngestCommand,
    _apply_limit,
    _select_targets,
)
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus


def test_command_name_and_signature():
    assert MentorIngestCommand.name() == "mentor:ingest"
    assert "{program:str}" in MentorIngestCommand.signature
    assert "{--force:bool}" in MentorIngestCommand.signature


def test_parses_program_and_flags():
    command = MentorIngestCommand()
    command.parse(["base", "--lesson", "aula-1", "--force"])
    assert command.input["program"] == "base"
    assert command.input["lesson"] == "aula-1"
    assert command.input["force"] is True


def test_force_defaults_to_false():
    command = MentorIngestCommand()
    command.parse(["base"])
    assert command.input["force"] is False


def _lesson(video_slug: str, status: TranscriptStatus) -> Lesson:
    return Lesson(
        uuid=uuid4(),
        platform_video_id=f"id-{video_slug}",
        program_slug="base",
        module_slug="m1",
        video_slug=video_slug,
        title="Tokens",
        transcript_status=status,
    )


# --- seleção de alvo (Controller Ruling B1) — pura, sem sessão de banco ---


def test_lesson_and_force_on_a_ready_lesson_selects_it():
    ready = _lesson("aula-1", TranscriptStatus.READY)
    targets, message = _select_targets(
        synced=[ready], pending=[], only="aula-1", force=True, program="base"
    )
    assert targets == [ready]
    assert message is None


def test_lesson_without_force_on_a_ready_lesson_selects_nothing():
    ready = _lesson("aula-1", TranscriptStatus.READY)
    targets, message = _select_targets(
        synced=[ready], pending=[], only="aula-1", force=False, program="base"
    )
    assert targets == []
    assert message == "aula 'aula-1' já está ready (use --force para reprocessar)"


def test_lesson_on_a_pending_lesson_selects_it():
    pending = _lesson("aula-1", TranscriptStatus.PENDING)
    targets, message = _select_targets(
        synced=[pending], pending=[pending], only="aula-1", force=False, program="base"
    )
    assert targets == [pending]
    assert message is None


def test_lesson_that_does_not_exist_selects_nothing():
    existing = _lesson("aula-1", TranscriptStatus.PENDING)
    targets, message = _select_targets(
        synced=[existing], pending=[existing], only="ghost", force=False, program="base"
    )
    assert targets == []
    assert message == "aula 'ghost' não existe no programa base"


def test_no_lesson_flag_returns_the_pending_list():
    pending_lessons = [_lesson("aula-1", TranscriptStatus.PENDING), _lesson("aula-2", TranscriptStatus.FAILED)]
    targets, message = _select_targets(
        synced=pending_lessons, pending=pending_lessons, only=None, force=False, program="base"
    )
    assert targets == pending_lessons
    assert message is None


# --- --limit (finding 8: `--limit 0` não pode ser "sem limite") ---


def test_no_limit_returns_every_target():
    lessons = [_lesson("aula-1", TranscriptStatus.PENDING), _lesson("aula-2", TranscriptStatus.PENDING)]
    targets, note = _apply_limit(lessons, None, "base")
    assert targets == lessons
    assert note is None


def test_positive_limit_truncates_the_target_list():
    lessons = [_lesson("aula-1", TranscriptStatus.PENDING), _lesson("aula-2", TranscriptStatus.PENDING)]
    targets, note = _apply_limit(lessons, 1, "base")
    assert targets == [lessons[0]]
    assert note is None


def test_limit_zero_processes_nothing_instead_of_meaning_unlimited():
    lessons = [_lesson("aula-1", TranscriptStatus.PENDING)]
    targets, note = _apply_limit(lessons, 0, "base")
    assert targets == []
    assert note == "--limit 0: nenhuma aula será processada em base"
