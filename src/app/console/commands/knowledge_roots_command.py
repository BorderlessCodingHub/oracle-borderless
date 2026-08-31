from src.domain.documents.repositories.document_repository import DocumentRepository
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal


class KnowledgeRootsCommand(Command):
    signature = "knowledge:roots"
    description = (
        "Lista as páginas de topo que a integração do Notion enxerga — o escopo "
        "da KB — com a contagem de documentos ingeridos sob cada uma."
    )

    def __init__(self, notion=None, documents=None) -> None:
        super().__init__()
        # Injetáveis em teste; o autodiscovery do kernel instancia sem argumentos.
        self._notion = notion or NotionClient()
        self._documents = documents

    async def handle(self) -> None:
        roots = await self._notion.list_workspace_root_pages()
        if not roots:
            print(
                "A integração não enxerga nenhuma página de nível de workspace.\n"
                "Token revogado, MCP fora do ar, ou nada compartilhado — o sync "
                "abortaria neste estado."
            )
            return

        counts = await self._counts()
        print(f"Roots em consumo: {len(roots)}\n")
        for root in roots:
            print(f"  {counts.get(root.id, 0):>5} doc(s)  {root.title}  [{root.id}]")

        orphans = {k: v for k, v in counts.items() if k not in {r.id for r in roots}}
        if orphans:
            # Documento cuja procedência não está mais entre os roots visíveis:
            # página despublicada desde o último sync. Some no sync seguinte.
            print("\nDocumentos de procedência não mais visível (saem no próximo sync):")
            for root_id, count in orphans.items():
                print(f"  {count:>5} doc(s)  [{root_id or '(sem procedência)'}]")

    async def _counts(self) -> dict[str, int]:
        if self._documents is not None:
            return await self._documents.count_by_root()
        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                return await DocumentRepository().count_by_root()
            finally:
                CurrentAsyncSessionContext.clear()
