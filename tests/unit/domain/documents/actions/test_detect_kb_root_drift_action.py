import pytest

from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.support.clients.notion.notion_client import WorkspaceRootPage
from src.support.core.settings import settings


class _FakeNotion:
    def __init__(self, pages: list[WorkspaceRootPage]) -> None:
        self._pages = pages

    async def list_workspace_root_pages(self) -> list[WorkspaceRootPage]:
        return self._pages


@pytest.mark.asyncio
async def test_reports_pages_visible_but_absent_from_the_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    notion = _FakeNotion([
        WorkspaceRootPage(id="abc123", title="Products"),
        WorkspaceRootPage(id="def456", title="Borderless Copy Bible"),
    ])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert [p.title for p in drift.unlisted] == ["Borderless Copy Bible"]
    assert drift.missing == []
    assert drift.has_drift is True


@pytest.mark.asyncio
async def test_reports_allowlisted_roots_the_integration_cannot_see(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123,ghi789", raising=False)
    notion = _FakeNotion([WorkspaceRootPage(id="abc123", title="Products")])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert drift.unlisted == []
    assert drift.missing == ["ghi789"]
    assert drift.has_drift is True


@pytest.mark.asyncio
async def test_no_drift_when_allowlist_matches_visibility(monkeypatch):
    monkeypatch.setattr(settings, "NOTION_KB_ROOT_PAGE_IDS", "abc123", raising=False)
    notion = _FakeNotion([WorkspaceRootPage(id="abc123", title="Products")])

    drift = await DetectKbRootDriftAction(notion=notion).execute()

    assert drift.unlisted == []
    assert drift.missing == []
    assert drift.has_drift is False
