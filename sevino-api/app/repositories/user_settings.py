import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_settings import UserSettings


class UserSettingsRepository:
    @staticmethod
    async def get_by_user_id(
        db: AsyncSession, user_id: uuid.UUID
    ) -> UserSettings | None:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, user_id: uuid.UUID, **fields
    ) -> UserSettings:
        settings = await UserSettingsRepository.get_by_user_id(db, user_id)
        if settings is None:
            settings = UserSettings(user_id=user_id, **fields)
            db.add(settings)
        else:
            for key, value in fields.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        await db.flush()
        return settings
