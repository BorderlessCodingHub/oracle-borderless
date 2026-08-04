from src.domain.documents.actions.list_knowledge_sections_action import (
    ListKnowledgeSectionsAction,
)
from src.domain.documents.repositories.document_chunk_repository import (
    DocumentChunkRepository,
)
from src.domain.documents.repositories.document_repository import DocumentRepository
from src.domain.observability.dtos.ops_overview import KnowledgeCounts


class CountKnowledgeBaseAction:
    """Contagens da base para a página de ops. Fronteira do subdomínio documents:
    quem quer esses números compõe esta Action, que delega aos repositórios —
    mesmo padrão da `ListKnowledgeSectionsAction` irmã. Escopo do root vigente
    é invariante de leitura (ADR-0012), já aplicado por
    `DocumentRepository.count_active/count_archived` e
    `DocumentChunkRepository.count_in_scope`: documento fora do root não entra
    em nenhuma contagem, mesmo que ainda esteja ativo no banco.
    """

    def __init__(self, documents=None, chunks=None, sections=None) -> None:
        self.documents = documents or DocumentRepository()
        self.chunks = chunks or DocumentChunkRepository()
        self.sections = sections or ListKnowledgeSectionsAction()

    async def execute(self) -> KnowledgeCounts:
        return KnowledgeCounts(
            documents_active=await self.documents.count_active(),
            documents_archived=await self.documents.count_archived(),
            chunks=await self.chunks.count_in_scope(),
            sections=await self.sections.execute(),
        )
