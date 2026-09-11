from src.domain.users.entities.user_session import UserSession
from src.domain.users.models.user_session import UserSessionModel


class UserSessionMapper:
    @staticmethod
    def to_entity(model: UserSessionModel) -> UserSession:
        return UserSession(
            uuid=model.uuid,
            token_hash=model.token_hash,
            platform_access_token=model.platform_access_token,
            user_id=model.user_id,
            user_email=model.user_email,
            user_name=model.user_name,
            user_username=model.user_username,
            last_platform_check_at=model.last_platform_check_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
            source=model.source,
            user_membership=model.user_membership,
            user_seniority=model.user_seniority,
            user_career_stage=model.user_career_stage,
        )

    @staticmethod
    def to_model_attrs(entity: UserSession) -> dict:
        return {
            "uuid": entity.uuid,
            "token_hash": entity.token_hash,
            "platform_access_token": entity.platform_access_token,
            "user_id": entity.user_id,
            "user_email": entity.user_email,
            "user_name": entity.user_name,
            "user_username": entity.user_username,
            "last_platform_check_at": entity.last_platform_check_at,
            "source": entity.source,
            "user_membership": entity.user_membership,
            "user_seniority": entity.user_seniority,
            "user_career_stage": entity.user_career_stage,
        }
