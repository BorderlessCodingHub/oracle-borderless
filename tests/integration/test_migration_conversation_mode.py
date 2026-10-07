"""Migração 0014: coluna `mode` em `conversations` (spec 2026-10-05 §5.1)."""

import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "0014_conversation_mode.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0014", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


async def _insert_conversation(db_session) -> UUID:
    conversation_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO conversations (uuid, user_email, title, mode) "
            "VALUES (:uuid, 'backfill@test.local', 'legado', NULL)"
        ),
        {"uuid": conversation_id},
    )
    return conversation_id


async def _insert_trace(db_session, conversation_id: UUID, intent: str) -> None:
    await db_session.execute(
        text(
            "INSERT INTO agent_traces ("
            " uuid, conversation_id, question, history_messages, history_tokens_est,"
            " gate_retrieve, gate_degraded, gate_ms, retrieval_ran, retrieval_top_k,"
            " retrieval_kept, retrieval_threshold, outcome, citations_count, tool_calls,"
            " intent, lesson_id"
            ") VALUES ("
            " :uuid, :conversation_id, 'pergunta', 0, 0,"
            " false, false, 0, false, 0,"
            " 0, 0.5, 'answered', 0, 0,"
            " :intent, :lesson_id"
            ")"
        ),
        {
            "uuid": uuid4(),
            "conversation_id": conversation_id,
            "intent": intent,
            "lesson_id": "M1A4" if intent == "mentor" else None,
        },
    )


@pytest.mark.asyncio
async def test_backfill_classifies_legacy_conversations_by_trace_intents(db_session):
    migration = _load_migration()

    navigate_only = await _insert_conversation(db_session)
    await _insert_trace(db_session, navigate_only, "navigate")
    await _insert_trace(db_session, navigate_only, "navigate")

    mentor_only = await _insert_conversation(db_session)
    await _insert_trace(db_session, mentor_only, "mentor")

    mixed = await _insert_conversation(db_session)
    await _insert_trace(db_session, mixed, "knowledge")
    await _insert_trace(db_session, mixed, "navigate")

    no_traces = await _insert_conversation(db_session)

    for statement in migration.BACKFILL_STATEMENTS:
        await db_session.execute(text(statement))

    rows = await db_session.execute(
        text("SELECT uuid, mode FROM conversations WHERE uuid = ANY(:ids)"),
        {"ids": [navigate_only, mentor_only, mixed, no_traces]},
    )
    modes = {row.uuid: row.mode for row in rows}

    assert modes == {
        navigate_only: "navigate",
        mentor_only: "mentor",
        mixed: "chat",
        no_traces: "chat",
    }
