from uuid import uuid4

import pytest

from src.domain.lessons.actions.search_lesson_action import SearchLessonAction


class FakeEmbeddings:
    def __init__(self):
        self.queries: list[str] = []

    async def embed_query(self, text: str):
        self.queries.append(text)
        return [0.1, 0.2]


class FakeRepo:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls: list[tuple] = []

    async def search_similar(self, lesson_id, embedding, top_k=None):
        self.calls.append((lesson_id, embedding, top_k))
        return self.rows


@pytest.mark.asyncio
async def test_embeds_the_query_and_scopes_to_the_lesson():
    embeddings, repo = FakeEmbeddings(), FakeRepo()
    lesson_id = uuid4()

    await SearchLessonAction(embeddings=embeddings, chunk_repo=repo).execute(
        lesson_id=lesson_id, query="o que é autorregressão?"
    )

    assert embeddings.queries == ["o que é autorregressão?"]
    assert repo.calls[0][0] == lesson_id


@pytest.mark.asyncio
async def test_an_empty_lesson_returns_nothing_without_raising():
    action = SearchLessonAction(embeddings=FakeEmbeddings(), chunk_repo=FakeRepo(rows=[]))
    assert await action.execute(lesson_id=uuid4(), query="x") == []


@pytest.mark.asyncio
async def test_keeps_the_query_embedding_for_the_trace():
    action = SearchLessonAction(embeddings=FakeEmbeddings(), chunk_repo=FakeRepo(rows=[]))
    assert action.last_query_embedding is None
    await action.execute(lesson_id=uuid4(), query="x")
    assert action.last_query_embedding == [0.1, 0.2]
