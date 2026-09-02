"""`knowledge:ingest` não pode furar a curadoria (ADR-0015): um id avulso
digitado/colado não passou pela travessia de descoberta, então pode ser qualquer
página que a integração alcance — inclusive linha de banco (tracker/PII)."""

import pytest

from src.app.console.commands.knowledge_ingest_command import KnowledgeIngestCommand
from src.support.clients.notion.notion_client import NotionPage
from src.support.core.exceptions import ValidationError


class _FakeNotionRejected:
    """Simula o veredito da curadoria: página reprovada (ex.: linha de banco)."""

    def __init__(self) -> None:
        self.checked: list[str] = []

    async def get_page_with_provenance(self, page_id: str) -> NotionPage:
        self.checked.append(page_id)
        return NotionPage(
            id=page_id, title="Onboarding Control", content="PII", url="https://n",
            is_approved=False, last_edited_time=None, kb_root_page_id=None,
        )


@pytest.mark.asyncio
async def test_refuses_a_page_rejected_by_curation_and_does_not_persist(monkeypatch):
    notion = _FakeNotionRejected()
    command = KnowledgeIngestCommand(notion=notion)
    command.input = {"page_id": "linha-de-tracker"}

    # Sentinela: se o comando chegar a abrir sessão de banco, o teste teria que
    # ter DB disponível. Ele NÃO deve chegar lá — falhar antes é o ponto.
    def _boom():
        raise AssertionError("não deveria abrir sessão para página reprovada")

    monkeypatch.setattr(
        "src.app.console.commands.knowledge_ingest_command.AsyncSessionLocal", _boom
    )

    with pytest.raises(ValidationError, match="curadoria") as exc:
        await command.handle()

    assert notion.checked == ["linha-de-tracker"]
    # Achado 4 (fechamento da Task 4): título de linha de banco pode ser PII —
    # não pode vazar na mensagem da exceção.
    assert "Onboarding Control" not in str(exc.value)


@pytest.mark.asyncio
async def test_persists_the_top_level_page_that_contains_the_page(monkeypatch):
    """A procedência vem da página de topo de onde ela descende — resolvida por
    `get_page_with_provenance`, que subiu a cadeia de `parent`."""

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
