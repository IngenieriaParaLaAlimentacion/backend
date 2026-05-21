from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus


class UserRepository:
    """Persistence operations for User entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        email: str,
        name: str,
        last_name: str,
        role: str = UserRole.ESTABLISHMENT_MANAGER,
        status: UserStatus = UserStatus.PENDING_VALIDATION,
    ) -> User:
        """Persist a new user. Password and establishments are handled separately."""
        user = User(
            email=email, name=name, last_name=last_name, role=role, status=status
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by id, or None if it does not exist."""
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email, or None if it does not exist."""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        role: UserRole | None = None,
        status: UserStatus | None = None,
    ) -> list[User]:
        """Return all users, optionally filtered by role or status."""
        query = select(User)
        if role is not None:
            query = query.where(User.role == role)
        if status is not None:
            query = query.where(User.status == status)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_paginated(
        self,
        *,
        role: UserRole | None = None,
        status: UserStatus | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[User], int]:
        """Return a paginated list of users."""
        query = select(User)
        count_query = select(func.count()).select_from(User)

        if role is not None:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)
        if status is not None:
            query = query.where(User.status == status)
            count_query = count_query.where(User.status == status)

        query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)

        total = (await self.db.execute(count_query)).scalar_one()
        users = (await self.db.execute(query)).scalars().all()

        return list(users), total

    async def update_status(self, user_id: UUID, status: UserStatus) -> None:
        """Update the status of a user."""
        await self.db.execute(
            update(User).where(User.id == user_id).values(status=status)
        )

    async def get_pending(self) -> list[User]:
        """Return all managers awaiting admin approval."""
        return await self.get_all(
            role=UserRole.ESTABLISHMENT_MANAGER,
            status=UserStatus.PENDING_VALIDATION,
        )
