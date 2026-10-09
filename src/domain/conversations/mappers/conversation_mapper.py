from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.models.conversation import ConversationModel


class ConversationMapper:
    @staticmethod
    def to_entity(model: ConversationModel) -> Conversation:
        return Conversation(
            uuid=model.uuid,
            user_email=model.user_email,
            title=model.title,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
            mode=model.mode,
        )

    @staticmethod
    def to_model_attrs(entity: Conversation) -> dict:
        return {
            "uuid": entity.uuid,
            "user_email": entity.user_email,
            "title": entity.title,
            "deleted_at": entity.deleted_at,
            "mode": entity.mode,
        }
