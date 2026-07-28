from src.domain.documents.entities.document import Document
from src.domain.documents.models.document import DocumentModel


class DocumentMapper:
    @staticmethod
    def to_entity(model: DocumentModel) -> Document:
        return Document(
            uuid=model.uuid,
            notion_page_id=model.notion_page_id,
            title=model.title,
            content=model.content,
            source_url=model.source_url,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
            last_edited_time=model.last_edited_time,
            kb_root_page_id=model.kb_root_page_id,
            kb_section=model.kb_section,
        )

    @staticmethod
    def to_model_attrs(entity: Document) -> dict:
        return {
            "uuid": entity.uuid,
            "notion_page_id": entity.notion_page_id,
            "title": entity.title,
            "content": entity.content,
            "source_url": entity.source_url,
            "status": entity.status,
            "deleted_at": entity.deleted_at,
            "last_edited_time": entity.last_edited_time,
            "kb_root_page_id": entity.kb_root_page_id,
            "kb_section": entity.kb_section,
        }
