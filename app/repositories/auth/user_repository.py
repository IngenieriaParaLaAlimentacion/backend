from uuid import UUID

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.establishment import UserEstablishmentStatus
from app.exceptions.domain_exceptions import UserAlreadyExistsError
from app.models.auth.user import User, UserRole, UserStatus
from app.models.auth.user_establishment import UserEstablishment
from app.utils.db import execute_paginated, ilike_condition


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
        """Persist a new user. Password and establishments are handled separately.

        The email is stored lowercased, matching how it is looked up.

        Raises:
            UserAlreadyExistsError: If the email is already taken. Guards against
                races where two requests pass their pre-check concurrently.
        """
        user = User(
            email=email.strip().lower(),
            name=name,
            last_name=last_name,
            role=role,
            status=status,
            locality=locality,
            description=description,
            contact_phone=contact_phone,
            is_email_verified=is_email_verified,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(user)
                await self.db.flush()
        except IntegrityError:
            raise UserAlreadyExistsError(email)
        await self.db.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Return a user by id, or None if it does not exist."""
        return await self.db.get(User, user_id)

    async def exists_by_email(self, email: str) -> bool:
        """Return whether any user already owns this email, ignoring case."""
        result = await self.db.execute(
            select(User.id)
            .where(func.lower(User.email) == email.strip().lower())
            .limit(1)
        )
        return result.first() is not None

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email, ignoring case, or None if it does not exist."""
        result = await self.db.execute(
            select(User)
            .where(func.lower(User.email) == email.strip().lower())
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
            condition = or_(
                ilike_condition(User.email, search),
                ilike_condition(User.name, search),
                ilike_condition(User.last_name, search),
            )
            query = query.where(condition)
            count_query = count_query.where(condition)

        return await execute_paginated(
            self.db, query, count_query, User.created_at.desc(), limit, offset
        )

    async def get_pending_establishments_page(
        self, *, limit: int, offset: int
    ) -> tuple[list[User], int]:
        """Return a paginated list of active field workers that have at least
        one pending establishment relation, and the total matching count."""
        has_pending = exists(
            select(1).where(
                UserEstablishment.user_id == User.id,
                UserEstablishment.status == UserEstablishmentStatus.PENDING,
            )
        )
        conditions = (
            User.role == UserRole.FIELD_WORKER,
            User.status == UserStatus.ACTIVE,
            has_pending,
        )

        return await execute_paginated(
            self.db,
            select(User),
            select(func.count()).select_from(User),
            User.created_at.desc(),
            limit,
            offset,
            conditions,
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
