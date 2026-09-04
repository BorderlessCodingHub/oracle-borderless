"""SignOutAction (ADR-0018): signout na plataforma (best-effort) + apaga a sessão."""

from datetime import datetime, timezone

import pytest
from uuid6 import uuid7

from src.domain.users.actions.sign_out_action import SignOutAction
from src.domain.users.entities.user_session import UserSession
from src.support.utils.session_tokens import hash_session_token

RAW = "token-cru"
NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
ROW = UserSession(
    uuid=uuid7(), token_hash=hash_session_token(RAW), platform_access_token="opaque-abc",
    user_id="u-1", user_email="ana@x.com", user_name=None, user_username=None,
    last_platform_check_at=NOW, created_at=NOW, updated_at=NOW,
)


class FakeSessions:
    def __init__(self, row):
        self.row, self.deleted = row, []

    async def get_by_token_hash(self, token_hash):
        return self.row if self.row and self.row.token_hash == token_hash else None

    async def delete(self, session_id):
        self.deleted.append(session_id)


class FakeClient:
    def __init__(self):
        self.signed_out = []

    async def sign_out(self, access_token):
        self.signed_out.append(access_token)


@pytest.mark.asyncio
async def test_signout_na_plataforma_e_apaga_a_sessao():
    sessions, client = FakeSessions(ROW), FakeClient()
    await SignOutAction(auth_client=client, sessions=sessions).execute(RAW)
    assert client.signed_out == ["opaque-abc"]
    assert sessions.deleted == [ROW.uuid]


@pytest.mark.asyncio
async def test_sessao_desconhecida_e_noop():
    sessions, client = FakeSessions(None), FakeClient()
    await SignOutAction(auth_client=client, sessions=sessions).execute("outro")
    assert client.signed_out == []
    assert sessions.deleted == []
