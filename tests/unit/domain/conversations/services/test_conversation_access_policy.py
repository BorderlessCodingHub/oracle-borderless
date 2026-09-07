"""Com auth (ADR-0017): conversa de outro usuário — ou órfã pré-auth — é 404."""

from datetime import datetime
from uuid import uuid4

import pytest

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.services.conversation_access_policy import (
    ConversationAccessPolicy,
)
from src.support.core.exceptions import NotFoundError


def _conversation(owner: str | None) -> Conversation:
    now = datetime(2026, 1, 1)
    return Conversation(uuid4(), owner, "t", now, now, None)


def test_dono_acessa():
    ConversationAccessPolicy.assert_can_access(_conversation("ana@x.com"), "ana@x.com")


def test_conversa_de_outro_usuario_e_not_found():
    with pytest.raises(NotFoundError):
        ConversationAccessPolicy.assert_can_access(_conversation("beto@x.com"), "ana@x.com")


def test_conversa_orfa_pre_auth_e_not_found():
    # user_email null é do período sem auth: some para todo mundo (spec §4.6).
    with pytest.raises(NotFoundError):
        ConversationAccessPolicy.assert_can_access(_conversation(None), "ana@x.com")
