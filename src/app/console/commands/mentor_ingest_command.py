"""`mentor:ingest` — sincroniza o catálogo de aulas de um programa e transcreve
as pendentes (spec da ingestão do mentor de aula, fase 4).

A seleção do alvo (Controller Ruling B1) foi isolada em `_select_targets`,
função pura sem sessão: `list_pending` só enxerga status pending/failed (+
`transcribing` obsoleto), então uma aula já `ready` nunca aparece nele — sem
essa separação, `--lesson X --force` numa aula pronta silenciosamente não
fazia nada.
"""

from src.domain.lessons.actions.ingest_lesson_action import IngestLessonAction
from src.domain.lessons.actions.sync_program_lessons_action import SyncProgramLessonsAction
from src.domain.lessons.entities.lesson import Lesson
from src.domain.lessons.enums import TranscriptStatus
from src.domain.lessons.repositories.lesson_repository import LessonRepository
from src.support.clients.borderless.borderless_lessons_client import BorderlessLessonsClient
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.clients.transcription.transcription_client import TranscriptionClient
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal
from src.support.core.settings import settings


def _select_targets(
    synced: list[Lesson],
    pending: list[Lesson],
    only: str | None,
    force: bool,
    program: str,
) -> tuple[list[Lesson], str | None]:
    """Decide quais aulas processar. Pura — sem sessão — para ser testável sem
    banco. `synced` é o catálogo inteiro (qualquer status), `pending` é o que
    `list_pending` já filtrou (pending/failed + transcribing obsoleto).

    Sem `--lesson`: o lote inteiro pendente. Com `--lesson`: só aquela aula, e
    só roda se ela estiver pendente OU se `--force` mandar reprocessar mesmo
    já pronta — daí não dá pra usar só `list_pending` para achá-la.
    """
    if not only:
        return pending, None

    matches = [lesson for lesson in synced if lesson.video_slug == only]
    if not matches:
        return [], f"aula '{only}' não existe no programa {program}"

    target = matches[0]
    if force:
        return [target], None

    pending_ids = {lesson.platform_video_id for lesson in pending}
    if target.platform_video_id in pending_ids:
        return [target], None

    return [], f"aula '{only}' já está {target.transcript_status} (use --force para reprocessar)"


class MentorIngestCommand(Command):
    signature = "mentor:ingest {program:str} {--lesson:str=} {--force:bool} {--limit:int=}"
    description = "Transcreve e indexa as aulas de um programa para o mentor de aula."

    def __init__(self, lessons_client=None, transcription=None) -> None:
        super().__init__()
        # Injetáveis em teste; o autodiscovery do kernel instancia sem argumento,
        # então os defaults precisam bastar.
        self._lessons_client = lessons_client or BorderlessLessonsClient()
        self._transcription = transcription or TranscriptionClient()

    async def handle(self) -> None:
        program = self.input["program"]
        only = self.input.get("lesson")
        force = bool(self.input.get("force"))
        limit = self.input.get("limit")

        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                repo = LessonRepository()
                sync = SyncProgramLessonsAction(lessons_client=self._lessons_client)
                synced = await sync.execute(program)
                await session.commit()

                pending = await repo.list_pending(program, max_attempts=settings.MENTOR_MAX_ATTEMPTS)
                targets, message = _select_targets(synced, pending, only, force, program)
                if message:
                    print(message)
                    return

                if limit:
                    targets = targets[:limit]

                action = IngestLessonAction(
                    embeddings=get_embeddings_client(),
                    lessons_client=self._lessons_client,
                    transcription=self._transcription,
                )

                done, skipped, failed = 0, 0, []
                for lesson in targets:
                    result = await action.execute(lesson, force=force)
                    # Commit por aula: um lote longo não pode perder tudo se a
                    # aula 28 derrubar o processo.
                    await session.commit()
                    if result.status == TranscriptStatus.FAILED:
                        failed.append((result.platform_video_id, result.failure_reason))
                    elif result.skipped:
                        skipped += 1
                    else:
                        done += 1
                    print(
                        f"  {lesson.video_slug}: {result.status}"
                        f"{' (sem mudança)' if result.skipped else f' — {result.chunks} chunks'}"
                    )

                print(f"\n{program}: {done} transcritas, {skipped} sem mudança, {len(failed)} falhas")
                for video_id, reason in failed:
                    print(f"  FALHA {video_id}: {reason}")
            except Exception:
                await session.rollback()
                raise
            finally:
                CurrentAsyncSessionContext.clear()
