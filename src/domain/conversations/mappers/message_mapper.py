from src.domain.conversations.entities.message import Message
from src.domain.conversations.models.message import MessageModel
from src.domain.shared.value_objects.citation import Citation


class MessageMapper:
    @staticmethod
    def _citation_to_dict(c: Citation) -> dict:
        return {
            "source_type": c.source_type,
            "title": c.title,
            "url": c.url,
            "snippet": c.snippet,
            "page_id": c.page_id,
        }

    @staticmethod
    def _dict_to_citation(d: dict) -> Citation:
        return Citation(
            source_type=d["source_type"],
            title=d["title"],
            url=d["url"],
            snippet=d["snippet"],
            page_id=d.get("page_id"),  # .get() — page_id is the only optional Citation field
        )

    @staticmethod
    def to_entity(model: MessageModel) -> Message:
        sources = (
            [MessageMapper._dict_to_citation(d) for d in model.sources]
            if model.sources is not None
            else None
        )
        return Message(
            uuid=model.uuid,
            conversation_id=model.conversation_id,
            role=model.role,
            content=model.content,
            created_at=model.created_at,
            sources=sources,
            navigation=model.navigation,
        )

    @staticmethod
    def to_model_attrs(entity: Message) -> dict:
        sources = (
            [MessageMapper._citation_to_dict(c) for c in entity.sources]
            if entity.sources is not None
            else None
        )
        return {
            "uuid": entity.uuid,
            "conversation_id": entity.conversation_id,
            "role": entity.role,
            "content": entity.content,
            "sources": sources,
            "navigation": entity.navigation,
        }
