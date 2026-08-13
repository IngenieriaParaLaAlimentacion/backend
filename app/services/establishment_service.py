from uuid import UUID

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.domain.establishment import (
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestWithRequesterDomain,
    EstablishmentDomain,
    EstablishmentListingParams,
    EstablishmentRequestDomain,
    EstablishmentRequestStatus,
)
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import (
    EstablishmentAlreadyExistsError,
    EstablishmentRequestAlreadyReviewedError,
    EstablishmentRequestNotFoundError,
    UniqueConstraintError,
)
from app.models import Establishment
from app.models.establishment_request import (
    EstablishmentRequest as EstablishmentRequestModel,
)
from app.schemas.establishment_schema import (
    EstablishmentCreationRequestCreate,
    EstablishmentRequest,
    EstablishmentUpdateRequest,
)
from app.services.email_service import (
    send_access_granted_email,
    send_creation_denied_email,
)


class EstablishmentService:
    """Service layer for establishment queries."""

    def __init__(
        self,
        uow: IUnitOfWork,
    ):
        self.uow = uow

    @staticmethod
    def _build_page(
        establishments: list[Establishment],
        total: int,
        page: int,
        page_size: int,
    ) -> PaginatedResult[EstablishmentDomain]:
        """Build a paginated EstablishmentDomain result from a repo page."""
        return PaginatedResult.build(
            items=[EstablishmentDomain.from_db(e) for e in establishments],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def _get_pending_request_or_raise(
        self, request_id: UUID
    ) -> EstablishmentRequestModel:
        """Return the request by ID, ensuring it is still pending review.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If the request is not
                pending.
        """
        request = await self.uow.establishment_request_repo.get_by_id(request_id)
        if request is None:
            raise EstablishmentRequestNotFoundError(str(request_id))
        if request.status != EstablishmentRequestStatus.PENDING:
            raise EstablishmentRequestAlreadyReviewedError(str(request_id))
        return request

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
        return self._build_page(establishments, total, page, page_size)

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
        return self._build_page(establishments, total, page, page_size)

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
        return PaginatedResult.build(
            items=[
                EstablishmentCreationRequestWithRequesterDomain.from_db(r)
                for r in requests
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def approve_creation_request(
        self, request_id: UUID, data: EstablishmentRequest, reviewer_id: UUID
    ) -> tuple[EstablishmentDomain, bool]:
        """Approve a pending establishment creation request.

        Creates the establishment described by ``data``, or reuses an
        existing one with the same place_id, grants the requesting field
        worker approved access to it, and notifies them by email.

        Returns an ``(establishment, reused)`` tuple: ``reused`` is True
        when an existing establishment was matched by place_id instead of
        creating a new one, so the admin-submitted data (other than
        place_id) was not applied.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If the request is not
                pending.
        """
        request = await self._get_pending_request_or_raise(request_id)

        establishment = await self.uow.establishment_repo.get_by_place_id(data.place_id)
        reused = establishment is not None
        if establishment is None:
            try:
                establishment = await self.uow.establishment_repo.create(
                    Establishment(**data.model_dump())
                )
            except UniqueConstraintError:
                # Concurrent approval created it first -> reuse it.
                establishment = await self.uow.establishment_repo.get_by_place_id(
                    data.place_id
                )
                if establishment is None:
                    raise
                reused = True

        await self.uow.user_establishment_repo.create_or_approve_relation(
            request.user_id, establishment.id
        )
        request.status = EstablishmentRequestStatus.APPROVED
        request.reviewed_by = reviewer_id
        await self.uow.commit()

        requester = await self.uow.user_repo.get_by_id(request.user_id)
        await send_access_granted_email(requester.email, [establishment.name])

        return EstablishmentDomain.from_db(establishment), reused

    async def reject_creation_request(
        self, request_id: UUID, reviewer_id: UUID, reason: str | None = None
    ) -> None:
        """Reject a pending establishment creation request and notify the
        requesting field worker by email, optionally including the admin's
        reason. No establishment is created or linked.

        Raises:
            EstablishmentRequestNotFoundError: If no request with that ID
                exists.
            EstablishmentRequestAlreadyReviewedError: If the request is not
                pending.
        """
        request = await self._get_pending_request_or_raise(request_id)
        request.status = EstablishmentRequestStatus.REJECTED
        request.reviewed_by = reviewer_id
        await self.uow.commit()

        requester = await self.uow.user_repo.get_by_id(request.user_id)
        await send_creation_denied_email(requester.email, request.name, reason)
