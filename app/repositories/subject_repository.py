import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject import Sex
from app.models.subject import Subject


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
