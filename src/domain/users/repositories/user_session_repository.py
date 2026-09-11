from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

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

    async def create_if_absent(self, user_session: UserSession) -> UserSession | None:
        """`create` tolerante à corrida pelo unique index de `token_hash`.

        Dois primeiros requests concorrentes com o MESMO bearer novo (barra e
        painel de chat logo depois do login na Platform) fazem o mesmo INSERT:
        o perdedor recebe `IntegrityError`. O savepoint isola esse erro — sem
        ele o Postgres aborta a transação inteira do request e o commit final
        vira ROLLBACK silencioso. Devolve `None` no conflito: quem chama relê
        a linha que o vencedor gravou.
        """
        model = UserSessionModel(**UserSessionMapper.to_model_attrs(user_session))
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
                await self.session.refresh(model)
        except IntegrityError:
            return None
        return UserSessionMapper.to_entity(model)

    async def mark_platform_checked(self, session_id: UUID, checked_at: datetime) -> None:
        await self.session.execute(
            update(UserSessionModel)
            .where(UserSessionModel.uuid == session_id)
            .values(last_platform_check_at=checked_at)
        )

    async def update_profile_snapshot(
        self,
        session_id: UUID,
        checked_at: datetime,
        membership: str | None,
        seniority: str | None,
        career_stage: str | None,
    ) -> None:
        await self.session.execute(
            update(UserSessionModel)
            .where(UserSessionModel.uuid == session_id)
            .values(
                last_platform_check_at=checked_at,
                user_membership=membership,
                user_seniority=seniority,
                user_career_stage=career_stage,
            )
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
