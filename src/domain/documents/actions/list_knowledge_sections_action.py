from src.domain.documents.repositories.document_repository import DocumentRepository


class ListKnowledgeSectionsAction:
    """Temas cobertos pela base — os ancestrais de 1º nível abaixo do root.

    Fronteira pública do subdomínio `documents` para quem precisa dizer ao
    usuário sobre o que o oráculo responde.
    """

    def __init__(self, documents=None) -> None:
        self.documents = documents or DocumentRepository()

    async def execute(self) -> list[str]:
        return await self.documents.list_sections()
