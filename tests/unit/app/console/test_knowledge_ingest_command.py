"""`knowledge:ingest` não pode furar o escopo da KB (ADR-0011/ADR-0012): um id
avulso digitado/colado não passou pela travessia de descoberta, então pode ser
qualquer página do workspace visível à integração."""

import pytest

from src.app.console.commands.knowledge_ingest_command import KnowledgeIngestCommand
from src.support.core.exceptions import ValidationError


class _FakeNotionOutOfScope:
    """Simula o veredito de escopo do NotionClient: sempre fora do escopo."""

    def __init__(self) -> None:
        self.checked: list[str] = []

    async def get_page_in_scope(self, page_id: str):
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
