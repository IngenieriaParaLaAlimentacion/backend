import datetime
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subject import Sex, SubjectListingParams, SubjectSortOrder
from app.exceptions.domain_exceptions import UniqueConstraintError
from app.models.measurement import Measurement
from app.models.subject import Subject
from app.utils.db import escape_like, execute_paginated

# Maps each SubjectSortOrder value to its SQLAlchemy order clause(s).
# Each pairs the sort column with `id` as a tiebreaker, so subjects sharing a
# value still page consistently instead of shuffling between requests.
# KeyError on an unmapped value is intentional: it surfaces missing cases immediately.
_SORT_CLAUSES = {
    SubjectSortOrder.CREATED_AT_DESC: (desc(Subject.created_at), desc(Subject.id)),
    SubjectSortOrder.CREATED_AT_ASC: (asc(Subject.created_at), asc(Subject.id)),
    SubjectSortOrder.NAME_ASC: (asc(Subject.name), asc(Subject.id)),
    SubjectSortOrder.NAME_DESC: (desc(Subject.name), desc(Subject.id)),
    SubjectSortOrder.BIRTH_DATE_ASC: (asc(Subject.birth_date), asc(Subject.id)),
    SubjectSortOrder.BIRTH_DATE_DESC: (desc(Subject.birth_date), desc(Subject.id)),
}


def subject_search_condition(search: str | None):
    """Case-insensitive name/last-name match for ``search``, or None.

    DNI is matched exactly, and only when the term is fully numeric. Returns
    None when ``search`` is empty so callers can skip the filter. Shared with
    the dashboard so both subject listings search identically.
    """
    if not search:
        return None
    search_term = f"%{escape_like(search)}%"
    condition = Subject.name.ilike(search_term, escape="\\") | Subject.last_name.ilike(
        search_term, escape="\\"
    )
    if search.isdigit():
        condition = condition | (Subject.dni == int(search))
    return condition


class SubjectRepository:
    """Persistence operations for Subject entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _listing_conditions(params: SubjectListingParams) -> list:
        """Build the filter conditions for a subject listing."""
        conditions = []

        search_condition = subject_search_condition(params.search)
        if search_condition is not None:
            conditions.append(search_condition)
        if params.birth_date_from is not None:
            conditions.append(Subject.birth_date >= params.birth_date_from)
        if params.birth_date_to is not None:
            conditions.append(Subject.birth_date <= params.birth_date_to)
        if params.establishment_id is not None:
            conditions.append(
                Subject.id.in_(
                    select(Measurement.subject_id).where(
                        Measurement.establishment_id == params.establishment_id
                    )
                )
            )
        if params.is_rural is not None:
            conditions.append(Subject.is_rural == params.is_rural)
        if params.is_indigenous is not None:
            conditions.append(Subject.is_indigenous == params.is_indigenous)
        if params.sex is not None:
            conditions.append(Subject.sex == params.sex)

        return conditions

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
        params: SubjectListingParams,
    ) -> tuple[list[Subject], int]:
        """Return a paginated list of subjects and the total matching count.

        ``search`` matches case-insensitively against name and last name (partial),
        and exactly against DNI (only if the search term is fully numeric).
        ``establishment_id`` matches a subject with at least one measurement there,
        not necessarily their most recent one.
        """
        base_query = select(Subject)
        count_query = select(func.count()).select_from(Subject)

        for condition in self._listing_conditions(params):
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        order_by = _SORT_CLAUSES[params.sort_order]
        return await execute_paginated(
            self.db, base_query, count_query, order_by, limit, offset
        )
