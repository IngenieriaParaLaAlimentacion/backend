import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject import Sex
from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.subject import Subject
from app.utils.db import escape_like, execute_paginated


class SubjectRepository:
    """Persistence operations for Subject entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        id: UUID | None,
        dni: int,
        sex: Sex,
        name: str,
        last_name: str,
        birth_date: datetime.date,
        is_rural: bool,
        is_indigenous: bool,
    ) -> Subject:
        """Persist a new subject. ``id`` is optional; when None the server generates it.

        The insert runs inside a SAVEPOINT so a unique violation rolls back only the
        failed row and leaves the session usable for the caller to re-query.

        Raises:
            UniqueConstraintError: If the id or DNI violates a unique constraint. The
            caller is responsible for re-querying to decide the outcome.
        """
        fields = dict(
            dni=dni,
            sex=sex,
            name=name,
            last_name=last_name,
            birth_date=birth_date,
            is_rural=is_rural,
            is_indigenous=is_indigenous,
        )
        if id is not None:
            fields["id"] = id
        subject = Subject(**fields)
        try:
            async with self.db.begin_nested():
                self.db.add(subject)
                await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("subject", (id, dni))
        await self.db.refresh(subject)
        return subject

    async def update(self, subject: Subject, data: dict) -> Subject:
        """Apply a partial update to an existing subject.

        Raises:
            UniqueConstraintError: If the new DNI already belongs to another subject.
        """
        for field, value in data.items():
            setattr(subject, field, value)
        try:
            await self.db.flush()
        except IntegrityError:
            raise UniqueConstraintError("dni", data.get("dni"))
        await self.db.refresh(subject)
        return subject

    async def get_by_id(self, subject_id: UUID) -> Subject | None:
        """Return a subject by id, or None if it does not exist."""
        return await self.db.get(Subject, subject_id)

    async def get_by_dni(self, dni: int) -> Subject | None:
        """Return a subject by DNI, or None if it does not exist."""
        result = await self.db.execute(select(Subject).where(Subject.dni == dni))
        return result.scalar_one_or_none()

    async def get_subject_listing(
        self,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> tuple[list[Subject], int]:
        """Return a paginated list of subjects and the total matching count.

        ``search`` matches case-insensitively against name and last name (partial),
        and exactly against DNI (only if the search term is fully numeric).
        """
        base_query = select(Subject)
        count_query = select(func.count()).select_from(Subject)

        if search:
            search_term = f"%{escape_like(search)}%"
            condition = Subject.name.ilike(
                search_term, escape="\\"
            ) | Subject.last_name.ilike(search_term, escape="\\")
            if search.isdigit():
                condition = condition | (Subject.dni == int(search))
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        return await execute_paginated(
            self.db, base_query, count_query, Subject.created_at.desc(), limit, offset
        )
