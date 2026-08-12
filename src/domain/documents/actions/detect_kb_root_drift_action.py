from src.domain.documents.dtos.kb_root_drift import KbRootDrift
from src.support.clients.notion.notion_client import NotionClient
from src.support.core.settings import settings


class DetectKbRootDriftAction:
    """Compara a allowlist de roots com o que a integração do Notion enxerga.

    Existe para substituir o aviso humano ("te aviso quando liberar mais coisa")
    por um sinal do sistema. Não altera a allowlist: incluir um root novo
    continua sendo decisão humana, feita na variável de ambiente.
    """

    def __init__(self, notion=None) -> None:
        self.notion = notion or NotionClient()

    async def execute(self) -> KbRootDrift:
        allowlist = set(settings.kb_root_page_ids)
        visible = await self.notion.list_workspace_root_pages()
        visible_ids = {page.id for page in visible}
        return KbRootDrift(
            unlisted=[page for page in visible if page.id not in allowlist],
            missing=[root for root in settings.kb_root_page_ids if root not in visible_ids],
        )
