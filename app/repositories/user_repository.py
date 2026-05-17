from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User, UserRole, UserStatus


class UserRepository:
    """Persistence operations for User entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user: User) -> User:
        """Persist a new user. Password and establishments are handled separately."""
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Return a user by id, or None if it does not exist"""
        return await self.db.get(User, user_id)
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Return a user by email, or None if it does not exist"""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    async def get_all(self,*,role: Optional[UserRole] = None,status: Optional[UserStatus] = None,)-> List[User]:
        """Return all users, optionally filtered by role or status"""
        query = select(User)
        if role is not None:
            query = query.where(User.role == role)
        if status is not None:
            query = query.where(User.status == status)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_pending(self) -> list[User]:
        """Return all managers awaiting admin approval"""
        return await self.get_all(
            role=UserRole.ESTABLISHMENT_MANAGER,
            status=UserStatus.PENDING_VALIDATION,
        )