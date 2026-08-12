from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.domain.documents.actions.ingest_document_action import IngestDocumentAction
from src.domain.documents.entities.document import Document
from src.support.clients.embeddings.embeddings_client import get_embeddings_client
from src.support.core.settings import settings

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
                # Primeiro root da allowlist: o seed de dev só precisa de uma
                # procedência válida para o documento ser recuperável.
                kb_root_page_id=next(iter(settings.kb_root_page_ids), None),
            )
            await action.execute(document)
