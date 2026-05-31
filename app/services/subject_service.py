from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectBase, SubjectDomain
from app.domain.subject_event import EventPayload, SubjectEventType
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.schemas.subject_schema import SubjectRequest, SubjectUpdateRequest


class SubjectService:
    """Service layer for subject registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def create_subject(
        self, data: SubjectRequest, actor_id: UUID
    ) -> SubjectDomain:
        """Register a new subject.

        Raises:
            SubjectAlreadyExistsError: If a subject with the given DNI already exists.
        """
        try:
            subject = await self.uow.subject_repo.create(
                dni=data.dni,
                sex=data.sex,
                name=data.name,
                last_name=data.last_name,
                birth_date=data.birth_date,
                is_rural=data.is_rural,
                is_indigenous=data.is_indigenous,
            )
        except UniqueConstraintError:
            raise SubjectAlreadyExistsError(data.dni)
        await self.uow.subject_event_repo.append(
            subject_id=subject.id,
            actor_id=actor_id,
            event_type=SubjectEventType.SUBJECT_CREATED,
        )
        await self.uow.commit()

        return SubjectDomain.from_db(subject)

    async def get_subject(self, subject_id: UUID) -> SubjectDomain:
        """Return a subject by id.

        Raises:
            SubjectNotFoundError: If no subject with the given id exists.
        """
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        return SubjectDomain.from_db(subject)

    async def get_subject_listing(
        self,
        page: int,
        page_size: int,
        search: str | None,
    ) -> PaginatedResult[SubjectBase]:
        """Return a paginated list of subjects with metadata.

        ``search`` matches case-insensitively against name, last name or DNI.
        Whitespace-only values are treated as no filter.
        """
        page = max(1, page)
        offset = (page - 1) * page_size
        search_term = (search or "").strip() or None
        subjects, total = await self.uow.subject_repo.get_subject_listing(
            limit=page_size, offset=offset, search=search_term
        )
        return PaginatedResult.build(
            items=[SubjectBase.from_db(subject) for subject in subjects],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def update_subject(
        self, subject_id: UUID, data: SubjectUpdateRequest, actor_id: UUID
    ) -> SubjectDomain:
        """Apply a partial update to an existing subject.

        Raises:
            SubjectNotFoundError: If no subject with the given id exists.
            EmptyUpdateRequestError: If no fields are provided.
            SubjectAlreadyExistsError: If the new DNI already belongs
            to another subject.
        """
        update_dict = data.to_update_dict()
        if not update_dict:
            raise EmptyUpdateRequestError()

        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))

        before = {field: getattr(subject, field) for field in update_dict}

        try:
            subject = await self.uow.subject_repo.update(subject, update_dict)
        except UniqueConstraintError:
            raise SubjectAlreadyExistsError(data.dni)

        after = {field: getattr(subject, field) for field in update_dict}

        await self.uow.subject_event_repo.append(
            subject_id=subject.id,
            actor_id=actor_id,
            event_type=SubjectEventType.SUBJECT_UPDATED,
            payload=EventPayload(before=before, after=after),
        )
        await self.uow.commit()

        return SubjectDomain.from_db(subject)
