from uuid import UUID

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.establishment import UserEstablishmentStatus
from app.domain.user import REVIEWED_ACCESS_ROLES
from app.exceptions.domain_exceptions import UserAlreadyExistsError
from app.models.auth.user import User, UserRole, UserStatus
from app.models.auth.user_establishment import UserEstablishment
from app.utils.db import execute_paginated, ilike_condition


class UserRepository:
    """Persistence operations for User entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _search_condition(self, search: str):
        """Case-insensitive match against email, name, and last_name (OR)."""
        return or_(
            ilike_condition(User.email, search),
            ilike_condition(User.name, search),
            ilike_condition(User.last_name, search),
        )

    def _pending_access_conditions(
        self, search: str | None, establishment_id: UUID | None
    ) -> tuple:
        """Conditions selecting active field workers and analysts awaiting
        establishment access.

        ``establishment_id`` narrows the population to users pending on that
        establishment; ``search`` matches their identity. Both are conditions on
        ``User``, so the listing and its count can share them.
        """
        # Aliased so the subquery stays independent when the caller already
        # selects from user_establishments (see count_pending_establishments).
        relation = aliased(UserEstablishment)
        pending_relation = [
            relation.user_id == User.id,
            relation.status == UserEstablishmentStatus.PENDING,
        ]
        if establishment_id is not None:
            pending_relation.append(relation.establishment_id == establishment_id)

        conditions = [
            User.role.in_(REVIEWED_ACCESS_ROLES),
            User.status == UserStatus.ACTIVE,
            exists(select(1).where(*pending_relation)),
        ]
        if search:
            conditions.append(self._search_condition(search))
        return tuple(conditions)

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

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email, ignoring case, or None if it does not exist."""
        result = await self.db.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
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
            condition = self._search_condition(search)
            query = query.where(condition)
            count_query = count_query.where(condition)

        return await execute_paginated(
            self.db, query, count_query, User.created_at.desc(), limit, offset
        )

    async def get_pending_establishments_page(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None = None,
        establishment_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        """Return a paginated list of active field workers and analysts that
        have at least one pending establishment relation, and the total matching count.

        ``search`` matches their email, name, or last_name; ``establishment_id``
        keeps only those pending on that establishment.
        """
        return await execute_paginated(
            self.db,
            select(User),
            select(func.count()).select_from(User),
            User.created_at.desc(),
            limit,
            offset,
            self._pending_access_conditions(search, establishment_id),
        )

    async def count_pending_establishments(
        self,
        *,
        search: str | None = None,
        establishment_id: UUID | None = None,
    ) -> int:
        """Return how many pending establishment relations belong to the field
        workers matched by the same filters as get_pending_establishments_page.

        Counts every pending relation of a matched worker, so the total always
        equals the establishments listed across all pages.
        """
        result = await self.db.execute(
            select(func.count())
            .select_from(UserEstablishment)
            .join(User, User.id == UserEstablishment.user_id)
            .where(
                UserEstablishment.status == UserEstablishmentStatus.PENDING,
                *self._pending_access_conditions(search, establishment_id),
            )
        )
        return result.scalar_one()

    async def update_status(self, user_id: UUID, status: UserStatus) -> None:
        """Update the status of a user."""
        await self.db.execute(
            update(User).where(User.id == user_id).values(status=status)
        )

    async def update_role(self, user_id: UUID, role: UserRole) -> None:
        """Update the role of a user."""
        await self.db.execute(update(User).where(User.id == user_id).values(role=role))

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
