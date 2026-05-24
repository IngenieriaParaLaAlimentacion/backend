from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectBase, SubjectDomain
from app.domain.subject_event import SubjectEventType
from app.exceptions.domain_exceptions import (
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
)
from app.schemas.subject_schema import SubjectRequest


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
        if await self.uow.subject_repo.get_by_dni(data.dni):
            raise SubjectAlreadyExistsError(data.dni)

        subject = await self.uow.subject_repo.create(**data.model_dump())
        await self.uow.subject_event_repo.append(
            subject_id=subject.id,
            actor_id=actor_id,
            event_type=SubjectEventType.SUBJECT_CREATED,
        )
        await self.uow.commit()

        return SubjectDomain.from_orm(subject)

    async def get_subject(self, subject_id: UUID) -> SubjectDomain:
        """Return a subject by id.

        Raises:
            SubjectNotFoundError: If no subject with the given id exists.
        """
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(subject_id)
        return SubjectDomain.from_orm(subject)

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
        offset = (page - 1) * page_size
        search = search.strip() or None if search else None
        subjects, total = await self.uow.subject_repo.get_subject_listing(
            limit=page_size, offset=offset, search=search
        )
        return PaginatedResult.build(
            items=[
                SubjectBase(
                    id=subject.id,
                    name=subject.name,
                    last_name=subject.last_name,
                    dni=subject.dni,
                    sex=subject.sex,
                )
                for subject in subjects
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
