"""Migração 0014: coluna `mode` em `conversations` (spec 2026-10-05 §5.1)."""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_conversations_mode_column_and_index_exist(db_session):
    row = (
        await db_session.execute(
            text(
                "SELECT data_type, is_nullable, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_name = 'conversations' AND column_name = 'mode'"
            )
        )
    ).one()
    assert row.data_type == "character varying"
    assert row.is_nullable == "YES"
    assert row.character_maximum_length == 16

    index = await db_session.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_conversations_user_email_mode'")
    )
    assert index.scalar_one() == 1
