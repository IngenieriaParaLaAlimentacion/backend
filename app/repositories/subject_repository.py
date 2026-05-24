import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject import Sex
from app.models.subject import Subject
from app.utils.db import escape_like, execute_paginated


class SubjectRepository:
    """Persistence operations for Subject entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        dni: int,
        sex: Sex,
        name: str,
        last_name: str,
        birth_date: datetime.date,
        is_rural: bool,
        is_indigenous: bool,
    ) -> Subject:
        """Persist a new subject."""
        subject = Subject(
            dni=dni,
            sex=sex,
            name=name,
            last_name=last_name,
            birth_date=birth_date,
            is_rural=is_rural,
            is_indigenous=is_indigenous,
        )
        self.db.add(subject)
        await self.db.flush()
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

        ``search`` matches case-insensitively against name, lastname or DNI (OR).
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
            self.db, base_query, count_query, Subject.created_at, limit, offset
        )
