import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_lesson_tables_and_hnsw_index_exist(db_session):
    for table in ("lessons", "lesson_chunks"):
        r = await db_session.execute(text("SELECT to_regclass(:t)"), {"t": table})
        assert r.scalar_one() is not None

    idx = await db_session.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_lesson_chunks_embedding_hnsw'")
    )
    assert idx.scalar_one() == 1
