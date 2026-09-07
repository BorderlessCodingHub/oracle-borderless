from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update

from src.domain.users.entities.user_session import UserSession
from src.domain.users.mappers import UserSessionMapper
from src.domain.users.models.user_session import UserSessionModel
from src.support.core.context import CurrentAsyncSessionContext


class UserSessionRepository:
    def __init__(self) -> None:
        self.session = CurrentAsyncSessionContext.get()

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        result = await self.session.execute(
            select(UserSessionModel).where(UserSessionModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return UserSessionMapper.to_entity(model) if model else None

    async def create(self, user_session: UserSession) -> UserSession:
        model = UserSessionModel(**UserSessionMapper.to_model_attrs(user_session))
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return UserSessionMapper.to_entity(model)

    async def mark_platform_checked(self, session_id: UUID, checked_at: datetime) -> None:
        await self.session.execute(
            update(UserSessionModel)
            .where(UserSessionModel.uuid == session_id)
            .values(last_platform_check_at=checked_at)
        )

    async def delete(self, session_id: UUID) -> None:
        await self.session.execute(
            delete(UserSessionModel).where(UserSessionModel.uuid == session_id)
        )

    async def delete_idle_since(self, cutoff: datetime) -> int:
        """Apaga sessões cuja última validação é anterior a `cutoff`. Devolve quantas."""
        result = await self.session.execute(
            delete(UserSessionModel).where(UserSessionModel.last_platform_check_at < cutoff)
        )
        return int(result.rowcount or 0)
