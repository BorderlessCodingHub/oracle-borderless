from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.entities.document import Document
from src.support.clients.embeddings.embeddings_client import get_embeddings_client

_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


class DevDocumentsSeed:
    """Ingere os markdown de database/seeds/knowledge/ como docs aprovados (dev/test)."""

    @staticmethod
    async def seed() -> None:
        action = IngestDocumentAction(embeddings=get_embeddings_client())
        now = datetime.now(timezone.utc)
        for path in sorted(_KNOWLEDGE_DIR.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            title = content.splitlines()[0].lstrip("# ").strip() if content else path.stem
            document = Document(
                uuid=uuid4(),
                notion_page_id=f"seed:{path.stem}",
                title=title,
                content=content,
                source_url=f"seed://{path.name}",
                status="approved",
                created_at=now,
                updated_at=now,
                deleted_at=None,
                # Procedência de dev: constante estável, sem fingir uma página do
                # Notion. Desde o ADR-0015 a procedência não afeta recuperação —
                # ela é só diagnóstico.
                kb_root_page_id="seed",
            )
            await action.execute(document)
