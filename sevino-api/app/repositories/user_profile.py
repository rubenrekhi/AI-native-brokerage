import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.user_profile import UserProfile


class UserProfileRepository:

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
        result = await db.execute(
            select(UserProfile).where(UserProfile.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_fields(
        db: AsyncSession, user_id: uuid.UUID, **fields
    ) -> UserProfile:
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError(
                "User profile not found",
                resource="user_profile",
            )
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        await db.flush()
        return profile
