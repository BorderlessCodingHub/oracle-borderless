"""`knowledge:ingest` não pode furar o escopo da KB (ADR-0011/ADR-0012): um id
avulso digitado/colado não passou pela travessia de descoberta, então pode ser
qualquer página do workspace visível à integração."""

import pytest

from src.app.console.commands.knowledge_ingest_command import KnowledgeIngestCommand
from src.support.clients.notion.notion_client import NotionPage
from src.support.core.exceptions import ValidationError


class _FakeNotionOutOfScope:
    """Simula o veredito de escopo do NotionClient: sempre fora do escopo."""

    def __init__(self) -> None:
        self.checked: list[str] = []

    async def get_page_with_provenance(self, page_id: str):
        self.checked.append(page_id)
        return None


@pytest.mark.asyncio
async def test_refuses_an_out_of_scope_page_and_does_not_persist(monkeypatch):
    notion = _FakeNotionOutOfScope()
    command = KnowledgeIngestCommand(notion=notion)
    command.input = {"page_id": "sop-fora-do-escopo"}

    # Sentinela: se o comando chegar a abrir sessão de banco, o teste teria que
    # ter DB disponível. Ele NÃO deve chegar lá — falhar antes é o ponto do fix.
    def _boom():
        raise AssertionError("não deveria abrir sessão para página fora do escopo")

    monkeypatch.setattr(
        "src.app.console.commands.knowledge_ingest_command.AsyncSessionLocal", _boom
    )

    with pytest.raises(ValidationError):
        await command.handle()

    assert notion.checked == ["sop-fora-do-escopo"]


@pytest.mark.asyncio
async def test_persists_the_root_that_contains_the_page(monkeypatch):
    """Com vários roots, a env var não diz sob qual deles esta página está —
    só `get_page_with_provenance` sabe, porque foi ela que subiu a ancestralidade."""

    class _FakeNotionInScope:
        async def get_page_with_provenance(self, page_id: str):
            return NotionPage(
                id=page_id, title="Página", content="corpo", url="https://n",
                is_approved=True, last_edited_time=None, kb_root_page_id="rootb",
            )

    captured: list = []

    class _FakeIngest:
        def __init__(self, embeddings=None) -> None:
            self.embeddings = embeddings

        async def execute(self, document):
            captured.append(document)
            return document

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    module = "src.app.console.commands.knowledge_ingest_command"
    monkeypatch.setattr(f"{module}.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(f"{module}.IngestDocumentAction", _FakeIngest)
    monkeypatch.setattr(f"{module}.get_embeddings_client", lambda: None)

    command = KnowledgeIngestCommand(notion=_FakeNotionInScope())
    command.input = {"page_id": "p1"}

    await command.handle()

    assert captured[0].kb_root_page_id == "rootb"
