"""PurgeStaleSessionsAction: corte = agora - 7 dias; idempotente."""

from datetime import datetime, timedelta, timezone

import pytest

from src.domain.users.actions.purge_stale_sessions_action import STALE_AFTER, PurgeStaleSessionsAction

NOW = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)


class FakeSessions:
    def __init__(self, removed: int):
        self.removed, self.cutoffs = removed, []

    async def delete_idle_since(self, cutoff):
        self.cutoffs.append(cutoff)
        return self.removed


@pytest.mark.asyncio
async def test_apaga_com_corte_de_7_dias_e_devolve_a_contagem():
    sessions = FakeSessions(removed=3)
    removed = await PurgeStaleSessionsAction(sessions=sessions, clock=lambda: NOW).execute()
    assert removed == 3
    assert sessions.cutoffs == [NOW - STALE_AFTER]
    assert STALE_AFTER == timedelta(days=7)
