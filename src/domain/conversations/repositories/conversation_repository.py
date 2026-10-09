from uuid import UUID

from sqlalchemy import select

from src.domain.conversations.entities.conversation import Conversation
from src.domain.conversations.mappers import ConversationMapper
from src.domain.conversations.models.conversation import ConversationModel
from src.support.core.context import CurrentAsyncSessionContext


class ConversationRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        result = await self.session.execute(
            select(ConversationModel).where(ConversationModel.uuid == conversation_id)
        )
        model = result.scalar_one_or_none()
        return ConversationMapper.to_entity(model) if model else None

    async def create(self, conversation: Conversation) -> Conversation:
        model = ConversationModel(**ConversationMapper.to_model_attrs(conversation))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return ConversationMapper.to_entity(model)

    async def list_by_user(
        self, user_email: str | None, mode: str | None = None
    ) -> list[Conversation]:
        stmt = select(ConversationModel).where(ConversationModel.deleted_at.is_(None))
        if user_email is None:
            stmt = stmt.where(ConversationModel.user_email.is_(None))
        else:
            stmt = stmt.where(ConversationModel.user_email == user_email)
        # Filtro estrito: linhas com mode NULL ficam fora de qualquer filtro.
        if mode is not None:
            stmt = stmt.where(ConversationModel.mode == mode)
        stmt = stmt.order_by(ConversationModel.updated_at.desc())
        rows = (await self.session.execute(stmt)).scalars().all()
        return [ConversationMapper.to_entity(m) for m in rows]
