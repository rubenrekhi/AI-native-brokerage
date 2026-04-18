import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_financial_profile import UserFinancialProfile


class FinancialProfileRepository:

    @staticmethod
    async def get_by_user_id(
        db: AsyncSession, user_id: uuid.UUID
    ) -> UserFinancialProfile | None:
        result = await db.execute(
            select(UserFinancialProfile).where(
                UserFinancialProfile.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, user_id: uuid.UUID, **fields
    ) -> UserFinancialProfile:
        profile = await FinancialProfileRepository.get_by_user_id(db, user_id)
        if profile is None:
            profile = UserFinancialProfile(user_id=user_id, **fields)
            db.add(profile)
        else:
            for key, value in fields.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
        await db.flush()
        return profile
