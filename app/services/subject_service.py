from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.subject import SubjectDomain
from app.exceptions.domain_exceptions import (
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
)
from app.schemas.subject_schema import SubjectRequest


class SubjectService:
    """Service layer for subject registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def create_subject(self, data: SubjectRequest) -> SubjectDomain:
        """Register a new subject.

        Raises:
            SubjectAlreadyExistsError: If a subject with the given DNI already exists.
        """
        if await self.uow.subject_repo.get_by_dni(data.dni):
            raise SubjectAlreadyExistsError(data.dni)

        subject = await self.uow.subject_repo.create(**data.model_dump())
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
