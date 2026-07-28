from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.mappers.notion_page_mapper import NotionPageMapper
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.console.command import Command
from src.support.core.context import CurrentAsyncSessionContext
from src.support.core.database import AsyncSessionLocal
from src.support.core.exceptions import ValidationError
from src.support.core.settings import settings


class KnowledgeIngestCommand(Command):
    signature = "knowledge:ingest {page_id:str}"
    description = "Ingere uma página aprovada do Notion (MCP) na base de conhecimento."

    def __init__(self, notion: NotionClient | None = None) -> None:
        super().__init__()
        # Injetável em teste; em produção o autodiscovery do kernel chama
        # `command_class()` sem argumentos, então o default precisa bastar.
        self._notion = notion or NotionClient()

    async def handle(self) -> None:
        page_id = self.input["page_id"]
        # Checa o escopo ANTES de abrir sessão: um id avulso (digitado ou colado)
        # não passou pela travessia de descoberta, então pode ser qualquer página
        # do workspace visível à integração — sem essa checagem, o comando
        # persistiria provenência com aparência legítima para conteúdo fora da
        # KB (ADR-0012 fechou esse mesmo buraco para `FetchNotionTool`).
        page = await self._notion.get_page_in_scope(page_id)
        if page is None:
            raise ValidationError(
                f"Página {page_id} está fora do escopo da base de conhecimento "
                "(fora da subárvore do root configurado) — ingestão abortada."
            )
        async with AsyncSessionLocal() as session:
            CurrentAsyncSessionContext.set(session)
            try:
                root_page_id = settings.NOTION_KB_ROOT_PAGE_ID or ""
                document = NotionPageMapper.to_document(page, root_page_id)
                action = IngestDocumentAction(embeddings=get_embeddings_client())
                result = await action.execute(document)
                await session.commit()
                print(f"Ingerido: {result.title} ({result.notion_page_id})")
            except Exception:
                await session.rollback()
                raise
            finally:
                CurrentAsyncSessionContext.clear()
