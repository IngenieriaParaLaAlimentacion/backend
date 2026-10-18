from collections.abc import AsyncIterator
from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import (
    EstablishmentApprovalResult,
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestWithRequesterDomain,
    EstablishmentDomain,
    EstablishmentListingParams,
    EstablishmentRequestDomain,
    EstablishmentRequestStatus,
    UserEstablishmentStatus,
)
from app.domain.establishment_characterization import (
    CharacterizationStatus,
    characterization_status,
)
from app.domain.pagination import PaginatedResult
from app.domain.user import UserActor
from app.exceptions.domain_exceptions import (
    EstablishmentAlreadyExistsError,
    UniqueConstraintError,
)
from app.models import Establishment
from app.models.establishments.establishment_request import (
    EstablishmentRequest as EstablishmentRequestModel,
)
from app.schemas.establishments.establishment_characterization_schema import (
    EstablishmentCharacterization,
)
from app.schemas.establishments.establishment_schema import (
    EstablishmentCreationRequestCreate,
    EstablishmentRequest,
    EstablishmentUpdateRequest,
)
from app.services.access import check_characterization_edit_access
from app.services.email_service import (
    send_creation_denied_email,
    send_establishment_created_email,
)
from app.services.exporters.csv.csv_exporter import CsvExporter


class EstablishmentService:
    """Service layer for establishment queries."""

    def __init__(
        self,
        uow: IUnitOfWork,
    ):
        self.uow = uow

    @staticmethod
    def _build_page(items, total: int, page: int, page_size: int, mapper):
        """Build a paginated result from a repo page, mapping each item."""
        return PaginatedResult.build(
            items=[mapper(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _set_access_pending(
        self, user_id: UUID, establishment_id: UUID, reused: bool
    ) -> None:
        """Set the field worker's access to the establishment as pending,
        for an admin to review separately, without touching an access that
        has already been resolved.

        Only checks for an existing relation when the establishment was
        reused (a fresh one can't have one yet): approved or pending
        relations are left as-is, and a rejected, revoked or withdrawn one is
        reopened to pending.
        """
        relation = None
        if reused:
            relation = await self.uow.user_establishment_repo.get_relation(
                user_id, establishment_id
            )

        if relation is None:
            await self.uow.user_establishment_repo.preset_relation(
                user_id, establishment_id
            )
        elif relation.status in (
            UserEstablishmentStatus.REJECTED,
            UserEstablishmentStatus.REVOKED,
            UserEstablishmentStatus.WITHDRAWN,
        ):
            await self.uow.user_establishment_repo.update_status_for_ids(
                user_id, [establishment_id], UserEstablishmentStatus.PENDING
            )
        # else: APPROVED or PENDING, already under review or resolved — leave as-is.

    async def _create_or_reuse_establishment(
        self, data: EstablishmentRequest
    ) -> tuple[Establishment, bool]:
        """Create the establishment described by ``data``, or reuse the
        existing one with the same place_id.

        A concurrent approval racing to create the same place first is
        treated the same as finding it upfront. Returns the establishment
        and whether it was reused.
        """
        existing = await self.uow.establishment_repo.get_by_place_id(data.place_id)
        if existing is not None:
            return existing, True

        try:
            created = await self.uow.establishment_repo.create(
                Establishment(**data.model_dump())
            )
            return created, False
        except UniqueConstraintError:
            establishment = await self.uow.establishment_repo.get_by_place_id(
                data.place_id
            )
            if establishment is None:
                raise
            return establishment, True

    async def create_establishment(
        self, data: EstablishmentRequest
    ) -> EstablishmentDomain:
        """Register a new establishment.

        Raises:
            EstablishmentAlreadyExistsError: If an establishment with the same
                place_id already exists.
        """
        existing = await self.uow.establishment_repo.get_by_place_id(data.place_id)
        if existing:
            raise EstablishmentAlreadyExistsError(data.place_id)

        try:
            establishment = await self.uow.establishment_repo.create(
                Establishment(**data.model_dump())
            )
        except UniqueConstraintError:
            # Concurrent create won the race for this place_id.
            raise EstablishmentAlreadyExistsError(data.place_id)
        await self.uow.commit()
        return EstablishmentDomain.from_db(establishment)

    async def create_establishment_request(
        self, user_id: UUID, data: EstablishmentCreationRequestCreate
    ) -> EstablishmentRequestDomain:
        """Register a notification requesting the creation of a missing
        establishment, attributed to the authenticated field worker.

        The notification is persisted with ``pending`` status and the
        creation timestamp.
        """
        request = await self.uow.establishment_request_repo.create(
            EstablishmentRequestModel(
                user_id=user_id,
                status=EstablishmentRequestStatus.PENDING,
                **data.model_dump(),
            )
        )
        await self.uow.commit()
        return EstablishmentRequestDomain.from_db(request)

    async def update_establishment(
        self, establishment_id: UUID, data: EstablishmentUpdateRequest
    ) -> EstablishmentDomain:
        """Apply a partial update to an existing establishment.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
            EstablishmentAlreadyExistsError: If the new place_id is already
                taken by a different establishment.
        """
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )

        if data.place_id is not None:
            duplicate = await self.uow.establishment_repo.get_by_place_id(data.place_id)
            if duplicate is not None and duplicate.id != establishment.id:
                raise EstablishmentAlreadyExistsError(data.place_id)

        for field, value in data.model_dump(exclude_none=True).items():
            if getattr(establishment, field) != value:
                setattr(establishment, field, value)

        establishment = await self.uow.establishment_repo.update(establishment)
        await self.uow.commit()
        return EstablishmentDomain.from_db(establishment)

    async def replace_characterization(
        self,
        establishment_id: UUID,
        actor: UserActor,
        data: EstablishmentCharacterization,
    ) -> EstablishmentDomain:
        """Replace an establishment's characterization profile as a whole.

        A profile with no answered field is stored as no profile.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
            EstablishmentAccessDeniedError: If the actor may not edit it.
        """
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        await check_characterization_edit_access(self.uow, actor, establishment_id)

        characterization = data.model_dump(mode="json")
        if characterization_status(characterization) == CharacterizationStatus.PENDING:
            characterization = None
        establishment.characterization = characterization

        establishment = await self.uow.establishment_repo.update(establishment)
        await self.uow.commit()
        return EstablishmentDomain.from_db(establishment)

    async def get_establishment_by_id(
        self, establishment_id: UUID
    ) -> EstablishmentDomain:
        """Return an establishment by ID.

        Raises:
            EstablishmentNotFoundError: If no establishment with that ID exists.
        """
        establishment = await self.uow.establishment_repo.get_by_id_or_raise(
            establishment_id
        )
        return EstablishmentDomain.from_db(establishment)

    async def get_establishments_paginated(
        self,
        page: int,
        page_size: int,
        params: EstablishmentListingParams,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return a paginated list of establishments with metadata.

        ``search`` matches case-insensitively against name or address.
        ``city`` and ``province`` are partial, case-insensitive matches.
        Whitespace-only values are treated as no filter.
        """
        offset = (page - 1) * page_size
        establishments, total = await self.uow.establishment_repo.get_paginated(
            limit=page_size, offset=offset, params=params
        )
        return self._build_page(
            establishments, total, page, page_size, EstablishmentDomain.from_db
        )

    def export_establishment_listing(
        self,
        params: EstablishmentListingParams,
        exporter: CsvExporter[EstablishmentDomain],
    ) -> AsyncIterator[bytes]:
        """Stream the establishment listing as an exported file's bytes.

        Applies the same filters and order as ``get_establishments_paginated``
        over the whole result set rather than one page. The caller's
        UnitOfWork must outlive the returned iterator.
        """
        rows = (
            EstablishmentDomain.from_db(e)
            async for e in self.uow.establishment_repo.stream_for_export(params)
        )
        return exporter.stream(rows)

    async def count_establishment_export(
        self, params: EstablishmentListingParams
    ) -> int:
        """How many rows the export will contain, for the row-count header."""
        return await self.uow.establishment_repo.count_for_export(params)

    async def get_available_establishments(
        self,
        user_id: UUID,
        page: int,
        page_size: int,
        params: EstablishmentListingParams,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Return establishments the user can still request, paginated."""
        offset = (page - 1) * page_size
        (
            establishments,
            total,
        ) = await self.uow.establishment_repo.get_available_for_user(
            user_id=user_id, limit=page_size, offset=offset, params=params
        )
        return self._build_page(
            establishments, total, page, page_size, EstablishmentDomain.from_db
        )

    async def list_establishment_requests_paginated(
        self,
        page: int,
        page_size: int,
        params: EstablishmentCreationRequestListingParams,
    ) -> PaginatedResult[EstablishmentCreationRequestWithRequesterDomain]:
        """Return a paginated list of establishment creation requests, each
        with its requester's identity.

        ``search`` is a partial, case-insensitive match against the reported
        name/address or the requester's name, last name or email. ``city``
        and ``province`` are partial, case-insensitive matches. ``status``
        is an exact match, filtering by review status.
        """
        offset = (page - 1) * page_size
        requests, total = await self.uow.establishment_request_repo.get_paginated(
            limit=page_size, offset=offset, params=params
        )
        return self._build_page(
            requests,
            total,
            page,
            page_size,
            EstablishmentCreationRequestWithRequesterDomain.from_db,
        )

    async def approve_creation_request(
        self, request_id: UUID, data: EstablishmentRequest, reviewer_id: UUID
    ) -> EstablishmentApprovalResult:
        """Approve a pending establishment creation request.

        Creates the establishment described by ``data``, or reuses an
        existing one with the same place_id, and leaves the requesting field
        worker's access to it pending a separate admin review. Notifies them
        by email that the establishment was created.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If the request is not
                pending.
        """
        request = await self.uow.establishment_request_repo.mark_reviewed_or_raise(
            request_id, EstablishmentRequestStatus.APPROVED, reviewer_id
        )

        establishment, reused = await self._create_or_reuse_establishment(data)

        await self._set_access_pending(request.user_id, establishment.id, reused)
        await self.uow.commit()

        requester = await self.uow.user_repo.get_by_id(request.user_id)
        await send_establishment_created_email(requester.email, establishment.name)

        return EstablishmentApprovalResult(
            EstablishmentDomain.from_db(establishment), reused
        )

    async def reject_creation_request(
        self, request_id: UUID, reviewer_id: UUID, reason: str | None = None
    ) -> None:
        """Reject a pending establishment creation request atomically and notify
        the requesting field worker by email, optionally including the admin's
        reason. No establishment is created or linked.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If the request is not
                pending.
        """
        request = await self.uow.establishment_request_repo.mark_reviewed_or_raise(
            request_id, EstablishmentRequestStatus.REJECTED, reviewer_id
        )
        await self.uow.commit()

        requester = await self.uow.user_repo.get_by_id(request.user_id)
        await send_creation_denied_email(requester.email, request.name, reason)
