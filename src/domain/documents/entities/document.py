from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Document:
    """Entidade de domínio. Pura. Sem SQLAlchemy."""

    uuid: UUID
    notion_page_id: str
    title: str
    content: str
    source_url: str
    status: str  # "approved" | "pending" | "archived"
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    last_edited_time: datetime | None = None  # last_edited_time do Notion (sync incremental)
    kb_root_page_id: str | None = None  # root da KB sob o qual foi ingerido (ADR-0012)
    kb_section: str | None = None  # seção = ancestral de 1º nível abaixo do root

    def is_approved(self) -> bool:
        return self.status == "approved" and self.deleted_at is None
