from src.domain.documents.actions.detect_kb_root_drift_action import (
    DetectKbRootDriftAction,
)
from src.support.core.console.command import Command
from src.support.core.settings import settings


class KnowledgeRootsCommand(Command):
    signature = "knowledge:roots"
    description = (
        "Compara os roots configurados da KB com as páginas que a integração do "
        "Notion enxerga no workspace. Reporta drift nos dois sentidos."
    )

    def __init__(self, action: DetectKbRootDriftAction | None = None) -> None:
        super().__init__()
        # Injetável em teste; o autodiscovery do kernel instancia sem argumentos.
        self._action = action or DetectKbRootDriftAction()

    async def handle(self) -> None:
        drift = await self._action.execute()

        print(f"Roots configurados: {len(settings.kb_root_page_ids)}")
        for root in settings.kb_root_page_ids:
            print(f"  - {root}")

        if drift.unlisted:
            print("\nVisíveis à integração mas FORA da allowlist:")
            for page in drift.unlisted:
                print(f"  ! {page.id}  {page.title}")
            print("\n  Para incluir, acrescente o id a NOTION_KB_ROOT_PAGE_IDS.")

        if drift.missing:
            print("\nNa allowlist mas INVISÍVEIS à integração:")
            for root in drift.missing:
                print(f"  ! {root}")
            print("\n  Permissão revogada, página movida, ou id errado na env var.")

        if not drift.has_drift:
            print("\nSem drift: allowlist e visibilidade coincidem.")
