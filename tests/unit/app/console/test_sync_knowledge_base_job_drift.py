import logging

import pytest

from src.app.console.jobs.sync_knowledge_base_job import SyncKnowledgeBaseJob
from src.domain.documents.dtos.kb_root_drift import KbRootDrift
from src.support.clients.notion.notion_client import WorkspaceRootPage


class _FakeDriftAction:
    def __init__(self, drift: KbRootDrift) -> None:
        self._drift = drift

    async def execute(self) -> KbRootDrift:
        return self._drift


@pytest.mark.asyncio
async def test_warns_when_a_liberated_root_is_outside_the_allowlist(caplog):
    drift = KbRootDrift(
        unlisted=[WorkspaceRootPage(id="def456", title="Borderless Copy Bible")]
    )

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(drift))

    assert "Borderless Copy Bible" in caplog.text


@pytest.mark.asyncio
async def test_warns_when_an_allowlisted_root_is_no_longer_visible(caplog):
    drift = KbRootDrift(missing=["ghi789"])

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(drift))

    assert "ghi789" in caplog.text


@pytest.mark.asyncio
async def test_warns_on_both_directions_when_both_exist(caplog):
    drift = KbRootDrift(
        unlisted=[WorkspaceRootPage(id="def456", title="Borderless Copy Bible")],
        missing=["ghi789"],
    )

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(drift))

    assert "Borderless Copy Bible" in caplog.text
    assert "ghi789" in caplog.text


@pytest.mark.asyncio
async def test_stays_quiet_without_drift(caplog):
    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_FakeDriftAction(KbRootDrift()))

    assert caplog.text == ""


@pytest.mark.asyncio
async def test_drift_failure_never_breaks_the_sync(caplog):
    class _Explodes:
        async def execute(self):
            raise RuntimeError("MCP fora do ar")

    with caplog.at_level(logging.WARNING):
        await SyncKnowledgeBaseJob()._warn_on_drift(_Explodes())  # não levanta
