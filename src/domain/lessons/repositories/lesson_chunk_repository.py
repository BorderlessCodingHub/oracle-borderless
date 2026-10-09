from urllib.parse import quote
from uuid import UUID

from sqlalchemy import delete, func, select

from src.domain.lessons.entities.lesson_chunk import LessonChunk
from src.domain.lessons.mappers.lesson_chunk_mapper import LessonChunkMapper
from src.domain.lessons.models.lesson import LessonModel
from src.domain.lessons.models.lesson_chunk import LessonChunkModel
from src.domain.shared.value_objects.citation import Citation
from src.support.agent.ports import KnowledgeSnippet
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.settings import settings


class LessonChunkRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def replace_for_lesson(self, lesson_id: UUID, chunks: list[LessonChunk]) -> None:
        await self.session.execute(
            delete(LessonChunkModel).where(LessonChunkModel.lesson_id == lesson_id)
        )
        for chunk in chunks:
            self.session.add(LessonChunkModel(**LessonChunkMapper.to_model_attrs(chunk)))
        await self.session.flush()

    async def count_for_lesson(self, lesson_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LessonChunkModel)
            .where(LessonChunkModel.lesson_id == lesson_id)
        )
        return result.scalar_one()

    async def search_similar(
        self, lesson_id: UUID, embedding: list[float], top_k: int | None = None
    ) -> list[tuple[KnowledgeSnippet, float]]:
        """Top-k dentro de UMA aula, com a distância de cada trecho.

        Sem corte por `RAG_MAX_DISTANCE`, ao contrário do `search_similar` de
        documents: lá o limiar impede que pergunta fora de assunto vire
        contexto; aqui o escopo já é uma aula só, e recusar é justamente o que
        o mentor não deve fazer (spec §4). A distância volta junto porque é o
        sinal de cobertura que alimenta o trace (spec §9.2).
        """
        limit = top_k if top_k is not None else settings.MENTOR_TOP_K
        distance = LessonChunkModel.embedding.cosine_distance(embedding)
        stmt = (
            select(
                LessonChunkModel.content,
                LessonChunkModel.start_seconds,
                LessonModel.title,
                LessonModel.program_slug,
                LessonModel.module_slug,
                LessonModel.video_slug,
                distance.label("distance"),
            )
            .join(LessonModel, LessonChunkModel.lesson_id == LessonModel.uuid)
            .where(
                LessonChunkModel.lesson_id == lesson_id,
                # embedding é nullable (aula ainda não processada / chunk sem
                # vetor); distância de cosseno contra NULL é indefinida.
                LessonChunkModel.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            (
                KnowledgeSnippet(
                    content=row.content,
                    citation=Citation(
                        source_type="lesson",
                        title=row.title,
                        # M8: cada segmento é escapado por si (safe="" — nem "/"
                        # escapa) para um slug com espaço/acento/caractere
                        # especial não quebrar a URL nem cruzar segmento.
                        url=(
                            f"/programs/{quote(row.program_slug, safe='')}/"
                            f"{quote(row.module_slug, safe='')}/"
                            f"{quote(row.video_slug, safe='')}?t={int(row.start_seconds)}"
                        ),
                        snippet=row.content[:200],
                    ),
                ),
                float(row.distance),
            )
            for row in rows
        ]
