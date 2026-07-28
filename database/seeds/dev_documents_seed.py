from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.entities.document import Document
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.settings import settings
from src.support.utils.notion_ids import normalize_page_id

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
                # Escopo (ADR-0012): conteúdo de dev/test é tratado como pertencente
                # ao root configurado, para permanecer recuperável pelo oráculo.
                kb_root_page_id=normalize_page_id(settings.NOTION_KB_ROOT_PAGE_ID),
            )
            await action.execute(document)
