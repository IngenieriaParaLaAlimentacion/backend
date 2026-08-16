from datetime import date
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.pagination import PaginatedResult
from app.domain.subject import SubjectDomain, SubjectListingParams
from app.domain.subject_detail import SubjectDetailDomain
from app.domain.subject_event import EventPayload, SubjectEventType
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.schemas.subjects.subject_schema import (
    SubjectRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)


def _to_json_safe(v):
    if isinstance(v, date):
        return v.isoformat()
    return v


class SubjectService:
    """Service layer for subject registration."""

    def __init__(self, uow: IUnitOfWork) -> None:
        self.uow = uow

    async def create_subject(
        self, data: SubjectRequest, actor_id: UUID
    ) -> tuple[SubjectDomain, bool]:
        """Idempotently register a subject.

        Returns a ``(subject, created)`` tuple: ``created`` is True for a brand-new
        subject (201) and False for an idempotent replay of an existing id (200).

        Raises:
            SubjectAlreadyExistsError: If the DNI already belongs to a different
            subject. The exception carries the canonical subject so the caller can
            remap local references.
        """
        # Idempotent replay: same client id already stored.
        if data.id is not None:
            existing = await self.uow.subject_repo.get_by_id(data.id)
            if existing is not None:
                return SubjectDomain.from_db(existing), False

        try:
            subject = await self.uow.subject_repo.create(
                id=data.id,
                dni=data.dni,
                sex=data.sex,
                name=data.name,
                last_name=data.last_name,
                birth_date=data.birth_date,
                is_rural=data.is_rural,
                is_indigenous=data.is_indigenous,
            )
        except UniqueConstraintError:
            # Concurrent insert of the same id (race) -> treat as replay.
            if data.id is not None:
                raced = await self.uow.subject_repo.get_by_id(data.id)
                if raced is not None:
                    return SubjectDomain.from_db(raced), False
            # Otherwise the DNI belongs to another subject -> surface the canonical one.
            canonical = await self.uow.subject_repo.get_by_dni(data.dni)
            canonical_body = (
                SubjectResponse.model_validate(canonical).model_dump(mode="json")
                if canonical is not None
                else None
            )
            raise SubjectAlreadyExistsError(data.dni, canonical=canonical_body)

        await self.uow.subject_event_repo.append(
            subject_id=subject.id,
            actor_id=actor_id,
            event_type=SubjectEventType.SUBJECT_CREATED,
        )
        await self.uow.commit()
        return SubjectDomain.from_db(subject), True

    async def get_subject(self, subject_id: UUID) -> SubjectDetailDomain:
        """Return a subject by id, enriched with their latest measurement.

        The latest measurement is the subject's most recent one across every
        establishment, so the derived status is their current clinical reading
        rather than a per-establishment one.

        Raises:
            SubjectNotFoundError: If no subject with the given id exists.
        """
        subject = await self.uow.subject_repo.get_by_id(subject_id)
        if subject is None:
            raise SubjectNotFoundError(str(subject_id))
        latest = await self.uow.measurement_repo.get_latest_for_subject(subject_id)
        return SubjectDetailDomain.build(subject, latest)

    async def get_subject_listing(
        self,
        page: int,
        page_size: int,
        params: SubjectListingParams,
    ) -> PaginatedResult[SubjectDetailDomain]:
        """Return a paginated list of subjects, each enriched with its
        latest measurement."""
        page = max(1, page)
        offset = (page - 1) * page_size
        subjects, total = await self.uow.subject_repo.get_subject_listing(
            limit=page_size, offset=offset, params=params
        )
        latest_by_subject = await self.uow.measurement_repo.get_latest_for_subjects(
            [subject.id for subject in subjects]
        )
        return PaginatedResult.build(
            items=[
                SubjectDetailDomain.build(subject, latest_by_subject.get(subject.id))
                for subject in subjects
            ],
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

        before = {f: _to_json_safe(getattr(subject, f)) for f in update_dict}

        try:
            subject = await self.uow.subject_repo.update(subject, update_dict)
        except UniqueConstraintError:
            raise SubjectAlreadyExistsError(data.dni)

        after = {f: _to_json_safe(getattr(subject, f)) for f in update_dict}

        await self.uow.subject_event_repo.append(
            subject_id=subject.id,
            actor_id=actor_id,
            event_type=SubjectEventType.SUBJECT_UPDATED,
            payload=EventPayload(before=before, after=after),
        )
        await self.uow.commit()

        return SubjectDomain.from_db(subject)
