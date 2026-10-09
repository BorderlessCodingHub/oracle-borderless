from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.repositories.conversation_repository import ConversationRepository


class ListConversationsAction:
    def __init__(self) -> None:
        self.conversations = ConversationRepository()

    async def execute(self, user_email: str | None, mode: str | None = None) -> list[Conversation]:
        return await self.conversations.list_by_user(user_email, mode=mode)
