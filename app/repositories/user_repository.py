from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, UserRole, UserStatus
from app.utils.db import escape_like, execute_paginated


class UserRepository:
    """Persistence operations for User entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        email: str,
        name: str,
        last_name: str,
        role: str = UserRole.FIELD_WORKER,
        status: UserStatus = UserStatus.PENDING_VALIDATION,
        locality: str | None = None,
        description: str | None = None,
        contact_phone: str | None = None,
        is_email_verified: bool = False,
    ) -> User:
        """Persist a new user. Password and establishments are handled separately."""
        user = User(
            email=email,
            name=name,
            last_name=last_name,
            role=role,
            status=status,
            locality=locality,
            description=description,
            contact_phone=contact_phone,
            is_email_verified=is_email_verified,
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
        result = await self.db.execute(
            select(User)
            .where(User.email == email)
            .options(selectinload(User.establishments))
        )
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
        limit: int,
        offset: int,
        role: UserRole | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        """Return a paginated list of users and the total matching count.

        ``search`` matches case-insensitively against email, name, and last_name (OR).
        """
        query = select(User)
        count_query = select(func.count()).select_from(User)

        if role is not None:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)
        if status is not None:
            query = query.where(User.status == status)
            count_query = count_query.where(User.status == status)
            if status == UserStatus.PENDING_VALIDATION:
                query = query.where(User.is_email_verified.is_(True))
                count_query = count_query.where(User.is_email_verified.is_(True))
        if search:
            search_term = f"%{escape_like(search)}%"
            condition = (
                (User.email.ilike(search_term, escape="\\"))
                | (User.name.ilike(search_term, escape="\\"))
                | (User.last_name.ilike(search_term, escape="\\"))
            )
            query = query.where(condition)
            count_query = count_query.where(condition)

        return await execute_paginated(
            self.db, query, count_query, User.created_at.desc(), limit, offset
        )

    async def update_status(self, user_id: UUID, status: UserStatus) -> None:
        """Update the status of a user."""
        await self.db.execute(
            update(User).where(User.id == user_id).values(status=status)
        )

    async def update_profile(self, user_id: UUID, values: dict[str, str]) -> None:
        """Update the given mutable profile columns for a user.

        ``values`` must contain only editable columns (name, last_name).
        """
        await self.db.execute(update(User).where(User.id == user_id).values(**values))

    async def update_email_verification(self, user_id: UUID) -> None:
        """Mark email as verified and record the verification timestamp."""
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                is_email_verified=True,
                email_verified_at=func.now(),
            )
        )
