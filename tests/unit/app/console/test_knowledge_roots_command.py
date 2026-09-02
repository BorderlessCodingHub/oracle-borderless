"""`knowledge:roots` deixou de reportar drift (ADR-0015): allowlist e
visibilidade viraram a mesma coisa. Ele agora responde "o oráculo está lendo o
que eu liberei?" — roots em consumo e quantos documentos vieram de cada um."""

import pytest

from src.app.console.commands.knowledge_roots_command import KnowledgeRootsCommand
from src.support.clients.notion.notion_client import WorkspaceRootPage


class _FakeNotion:
    async def list_workspace_root_pages(self):
        return [
            WorkspaceRootPage(id="products", title="Products"),
            WorkspaceRootPage(id="labs", title="Borderless Coding Labs"),
        ]


class _FakeDocuments:
    async def count_by_root(self):
        return {"products": 42}


@pytest.mark.asyncio
async def test_lists_roots_with_document_counts(capsys):
    await KnowledgeRootsCommand(notion=_FakeNotion(), documents=_FakeDocuments()).handle()

    out = capsys.readouterr().out
    assert "Products" in out and "42" in out
    # Root visível sem documento ingerido: sync ainda não rodou, ou tudo abaixo
    # dele foi barrado pela curadoria. Precisa aparecer, com zero — na MESMA
    # linha do root (não apenas "0" em algum lugar da saída, que discriminaria
    # só por acidente já que nenhum id da fixture tem dígito).
    lines = out.splitlines()
    labs_line = next(line for line in lines if "Borderless Coding Labs" in line)
    assert "0 doc(s)" in labs_line


@pytest.mark.asyncio
async def test_reports_when_the_integration_sees_nothing(capsys):
    class _Empty:
        async def list_workspace_root_pages(self):
            return []

    await KnowledgeRootsCommand(notion=_Empty(), documents=_FakeDocuments()).handle()

    assert "nenhuma página" in capsys.readouterr().out.lower()
