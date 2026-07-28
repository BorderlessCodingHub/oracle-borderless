from datetime import datetime, timezone
from uuid import uuid4

from src.domain.documents.entities.document import Document
from src.support.clients.notion.notion_client import NotionPage
from src.support.utils.notion_ids import normalize_page_id


class NotionPageMapper:
    @staticmethod
    def to_document(page: NotionPage, root_page_id: str) -> Document:
        now = datetime.now(timezone.utc)
        return Document(
            uuid=uuid4(),
            notion_page_id=page.id,
            title=page.title,
            content=page.content,
            source_url=page.url,
            status="approved" if page.is_approved else "pending",
            created_at=now,
            updated_at=now,
            deleted_at=None,
            last_edited_time=page.last_edited_time,
            kb_root_page_id=normalize_page_id(root_page_id),
            kb_section=page.section,
        )
