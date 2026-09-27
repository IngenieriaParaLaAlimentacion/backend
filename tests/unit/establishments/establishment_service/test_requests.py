import uuid
from datetime import datetime, timezone
from math import ceil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.establishment import (
    EstablishmentCreationRequestListingParams,
    EstablishmentCreationRequestWithRequesterDomain,
    EstablishmentDomain,
    EstablishmentRequestDomain,
    EstablishmentRequestStatus,
    UserEstablishmentStatus,
)
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import (
    EstablishmentRequestAlreadyReviewedError,
    EstablishmentRequestNotFoundError,
    UniqueConstraintError,
)
from app.schemas.establishments.establishment_schema import (
    EstablishmentCreationRequestCreate,
)
from app.services.establishments.establishment_service import EstablishmentService
from tests.unit.establishments.establishment_service.helpers import (
    _make_request,
)


def _make_requester(**overrides) -> MagicMock:
    """Build a mock User ORM row for an EstablishmentRequest's requester."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.name = "Maria"
    user.last_name = "Field Worker"
    user.email = "maria@test.com"
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def _make_request_orm(user_id: uuid.UUID, **overrides) -> MagicMock:
    """Build a mock EstablishmentRequest ORM row with the given attributes."""
    request = MagicMock()
    request.id = uuid.uuid4()
    request.user_id = user_id
    request.name = None
    request.formatted_address = None
    request.city = None
    request.province = None
    request.status = EstablishmentRequestStatus.PENDING
    request.created_at = datetime.now(timezone.utc)
    request.user = _make_requester(id=user_id)
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


@pytest.fixture
def make_request_review_uow():
    """Build a UoW mocked for approve/reject-creation-request flows: wires
    the pending-request lookup, the atomic status transition, and the
    requester email lookup shared by both."""

    def _make(request=None, requester=None):
        async def _mark_reviewed_or_raise(request_id, status, reviewer_id):
            if request is None:
                raise EstablishmentRequestNotFoundError(str(request_id))
            if request.status != EstablishmentRequestStatus.PENDING:
                raise EstablishmentRequestAlreadyReviewedError(str(request_id))
            request.status = status
            request.reviewed_by = reviewer_id
            return request

        uow = AsyncMock()
        uow.establishment_request_repo.get_by_id = AsyncMock(return_value=request)
        uow.establishment_request_repo.mark_reviewed_or_raise = AsyncMock(
            side_effect=_mark_reviewed_or_raise
        )
        uow.user_repo.get_by_id = AsyncMock(return_value=requester or _make_requester())
        uow.commit = AsyncMock()
        return uow

    return _make


class TestCreateEstablishmentRequest:
    @pytest.fixture
    def make_uow(self):
        def _make(created):
            uow = AsyncMock()
            uow.establishment_request_repo.create = AsyncMock(return_value=created)
            uow.commit = AsyncMock()
            return uow

        return _make

    async def test_delegates_to_repo_with_pending_status_and_user_id(
        self, make_uow, make_establishment
    ):
        """The ORM row carries the caller's user_id and PENDING status."""
        user_id = uuid.uuid4()
        created = _make_request_orm(user_id)
        uow = make_uow(created)
        service = EstablishmentService(uow=uow)

        await service.create_establishment_request(
            user_id,
            EstablishmentCreationRequestCreate(
                name="Comedor Esperanza", formatted_address="Av. Siempre Viva 742"
            ),
        )

        uow.establishment_request_repo.create.assert_called_once()
        call_arg = uow.establishment_request_repo.create.call_args[0][0]
        assert call_arg.user_id == user_id
        assert call_arg.status == EstablishmentRequestStatus.PENDING
        assert call_arg.name == "Comedor Esperanza"
        assert call_arg.formatted_address == "Av. Siempre Viva 742"

    async def test_name_and_address_are_not_optional(self, make_uow):
        """An empty payload still persists a request with None fields."""
        user_id = uuid.uuid4()
        created = _make_request_orm(user_id)
        uow = make_uow(created)
        service = EstablishmentService(uow=uow)

        await service.create_establishment_request(
            user_id,
            EstablishmentCreationRequestCreate(
                name="Comedor Esperanza", formatted_address="Av. Siempre Viva 742"
            ),
        )

        call_arg = uow.establishment_request_repo.create.call_args[0][0]
        assert call_arg.name is not None
        assert call_arg.formatted_address is not None
        assert call_arg.city is None
        assert call_arg.province is None

    async def test_commits(self, make_uow):
        """The created request is committed."""
        user_id = uuid.uuid4()
        uow = make_uow(_make_request_orm(user_id))
        service = EstablishmentService(uow=uow)

        await service.create_establishment_request(
            user_id,
            EstablishmentCreationRequestCreate(
                name="Comedor", formatted_address="Av. Pez Sherman 242"
            ),
        )

        uow.commit.assert_called_once()

    async def test_returns_domain(self, make_uow):
        """The service returns an EstablishmentRequestDomain built from the row."""
        user_id = uuid.uuid4()
        created = _make_request_orm(
            user_id,
            name="Comedor Esperanza",
            formatted_address="Av. Siempre Viva 742",
            city="Cordoba",
            province="Cordoba",
        )
        uow = make_uow(created)
        service = EstablishmentService(uow=uow)

        result = await service.create_establishment_request(
            user_id,
            EstablishmentCreationRequestCreate(
                name="Comedor Esperanza",
                formatted_address="Av. Siempre Viva 742",
                city="Cordoba",
                province="Cordoba",
            ),
        )

        assert isinstance(result, EstablishmentRequestDomain)
        assert result.id == created.id
        assert result.user_id == user_id
        assert result.status == "pending"
        assert result.name == "Comedor Esperanza"
        assert result.created_at is not None


class TestListEstablishmentRequestsPaginated:
    @pytest.fixture
    def make_uow(self):
        def _make(requests, total):
            uow = AsyncMock()
            uow.establishment_request_repo.get_paginated = AsyncMock(
                return_value=(requests, total)
            )
            return uow

        return _make

    async def test_returns_items(self, make_uow):
        requests = [_make_request_orm(uuid.uuid4()), _make_request_orm(uuid.uuid4())]
        service = EstablishmentService(uow=make_uow(requests, total=2))

        result = await service.list_establishment_requests_paginated(
            page=1,
            page_size=20,
            params=EstablishmentCreationRequestListingParams(),
        )

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 2
        assert result.page == 1
        assert result.page_size == 20

    async def test_calculates_total_pages(self, make_uow):
        requests = [_make_request_orm(uuid.uuid4()) for _ in range(5)]
        service = EstablishmentService(uow=make_uow(requests, total=23))

        result = await service.list_establishment_requests_paginated(
            page=1,
            page_size=5,
            params=EstablishmentCreationRequestListingParams(),
        )

        assert result.total_pages == ceil(23 / 5)

    async def test_empty(self, make_uow):
        service = EstablishmentService(uow=make_uow([], total=0))

        result = await service.list_establishment_requests_paginated(
            page=1,
            page_size=20,
            params=EstablishmentCreationRequestListingParams(),
        )

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    async def test_passes_correct_offset_and_forwards_params(self, make_uow):
        """The service computes the offset from page/page_size and forwards
        the params object to the repo unchanged."""
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)
        params = EstablishmentCreationRequestListingParams(search="Comedor")

        await service.list_establishment_requests_paginated(
            page=3, page_size=10, params=params
        )

        uow.establishment_request_repo.get_paginated.assert_called_once_with(
            limit=10, offset=20, params=params
        )

    async def test_items_are_domain_instances_with_requester_identity(self, make_uow):
        """Each item is an EstablishmentCreationRequestWithRequesterDomain
        with the reported fields and the requester's identity flattened
        from the eager-loaded ``user`` relationship."""
        user_id = uuid.uuid4()
        requester = _make_requester(
            id=user_id, name="Maria", last_name="Perez", email="maria@test.com"
        )
        request = _make_request_orm(
            user_id,
            name="Comedor Esperanza",
            formatted_address="Av. Siempre Viva 742",
            user=requester,
        )
        service = EstablishmentService(uow=make_uow([request], total=1))

        result = await service.list_establishment_requests_paginated(
            page=1,
            page_size=20,
            params=EstablishmentCreationRequestListingParams(),
        )

        [item] = result.items
        assert isinstance(item, EstablishmentCreationRequestWithRequesterDomain)
        assert item.id == request.id
        assert item.name == "Comedor Esperanza"
        assert item.formatted_address == "Av. Siempre Viva 742"
        assert item.requester_name == "Maria"
        assert item.requester_last_name == "Perez"
        assert item.requester_email == "maria@test.com"


class TestApproveCreationRequest:
    @pytest.fixture
    def make_uow(self, make_request_review_uow, make_establishment):
        def _make(
            request=None,
            existing_establishment=None,
            created_establishment=None,
            requester=None,
            existing_relation=None,
        ):
            uow = make_request_review_uow(request=request, requester=requester)
            uow.establishment_repo.get_by_place_id = AsyncMock(
                return_value=existing_establishment
            )
            uow.establishment_repo.create = AsyncMock(
                return_value=created_establishment or make_establishment()
            )
            uow.user_establishment_repo.get_relation = AsyncMock(
                return_value=existing_relation
            )
            uow.user_establishment_repo.preset_relation = AsyncMock()
            uow.user_establishment_repo.update_status_for_ids = AsyncMock()
            return uow

        return _make

    async def test_raises_when_request_not_found(self, make_uow):
        """Raises EstablishmentRequestNotFoundError when the repo returns None."""
        uow = make_uow(request=None)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentRequestNotFoundError):
            await service.approve_creation_request(
                uuid.uuid4(), _make_request(), reviewer_id=uuid.uuid4()
            )

    async def test_raises_when_already_reviewed(self, make_uow):
        """Raises EstablishmentRequestAlreadyReviewedError when the request
        is not pending."""
        request = _make_request_orm(
            uuid.uuid4(), status=EstablishmentRequestStatus.APPROVED
        )
        uow = make_uow(request=request)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentRequestAlreadyReviewedError):
            await service.approve_creation_request(
                request.id, _make_request(), reviewer_id=uuid.uuid4()
            )

    async def test_creates_new_establishment_when_no_place_id_match(
        self, make_uow, make_establishment
    ):
        """Creates a new establishment when no place_id match is found."""
        request = _make_request_orm(uuid.uuid4())
        created = make_establishment(name="Centro Nuevo")
        uow = make_uow(
            request=request, existing_establishment=None, created_establishment=created
        )
        service = EstablishmentService(uow=uow)

        result, reused = await service.approve_creation_request(
            request.id,
            _make_request(name="Centro Nuevo", place_id="place-new-001"),
            reviewer_id=uuid.uuid4(),
        )

        uow.establishment_repo.create.assert_called_once()
        assert isinstance(result, EstablishmentDomain)
        assert result.name == "Centro Nuevo"
        assert reused is False

    async def test_reuses_establishment_created_by_a_concurrent_approval(
        self, make_uow, make_establishment
    ):
        """If a concurrent approval creates the establishment first, the
        unique constraint on place_id makes create() fail; the service
        recovers by re-fetching and reusing the winner instead of erroring
        out."""
        request = _make_request_orm(uuid.uuid4())
        winner = make_establishment(name="Centro Nuevo")
        uow = make_uow(request=request, existing_establishment=None)
        uow.establishment_repo.get_by_place_id = AsyncMock(side_effect=[None, winner])
        uow.establishment_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("place_id", "place-new-001")
        )
        service = EstablishmentService(uow=uow)

        result, reused = await service.approve_creation_request(
            request.id,
            _make_request(name="Centro Nuevo", place_id="place-new-001"),
            reviewer_id=uuid.uuid4(),
        )

        assert result.id == winner.id
        assert reused is True

    async def test_reuses_existing_establishment_with_same_place_id(
        self, make_uow, make_establishment
    ):
        """Reuses the matching establishment instead of creating a duplicate."""
        existing = make_establishment(name="Centro Existente")
        request = _make_request_orm(uuid.uuid4())
        uow = make_uow(request=request, existing_establishment=existing)
        service = EstablishmentService(uow=uow)

        result, reused = await service.approve_creation_request(
            request.id,
            _make_request(place_id=existing.place_id),
            reviewer_id=uuid.uuid4(),
        )

        uow.establishment_repo.create.assert_not_called()
        assert result.id == existing.id
        assert reused is True

    async def test_leaves_access_pending_when_establishment_is_new(
        self, make_uow, make_establishment
    ):
        """A freshly created establishment can't have a prior relation yet,
        so a pending one is staged directly without checking for one."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        uow = make_uow(request=request, existing_establishment=None)
        service = EstablishmentService(uow=uow)

        result, reused = await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        assert reused is False
        uow.user_establishment_repo.get_relation.assert_not_called()
        uow.user_establishment_repo.preset_relation.assert_called_once_with(
            user_id, result.id
        )

    async def test_leaves_access_pending_when_reused_establishment_has_no_relation(
        self, make_uow, make_establishment
    ):
        """A reused establishment the requester never had a relation to
        (approved, pending, or rejected) gets a pending one staged fresh."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        existing = make_establishment()
        uow = make_uow(
            request=request, existing_establishment=existing, existing_relation=None
        )
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        uow.user_establishment_repo.preset_relation.assert_called_once_with(
            user_id, existing.id
        )

    async def test_reopens_a_rejected_relation_to_pending(
        self, make_uow, make_establishment
    ):
        """A field worker previously rejected for this establishment gets
        another chance at admin review instead of staying rejected."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        existing = make_establishment()
        relation = MagicMock(status=UserEstablishmentStatus.REJECTED)
        uow = make_uow(
            request=request,
            existing_establishment=existing,
            existing_relation=relation,
        )
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user_id, [existing.id], UserEstablishmentStatus.PENDING
        )
        uow.user_establishment_repo.preset_relation.assert_not_called()

    async def test_reopens_a_revoked_relation_to_pending(
        self, make_uow, make_establishment
    ):
        """A field worker whose access was revoked for this establishment gets
        another chance at admin review instead of staying revoked."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        existing = make_establishment()
        relation = MagicMock(status=UserEstablishmentStatus.REVOKED)
        uow = make_uow(
            request=request,
            existing_establishment=existing,
            existing_relation=relation,
        )
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user_id, [existing.id], UserEstablishmentStatus.PENDING
        )
        uow.user_establishment_repo.preset_relation.assert_not_called()

    async def test_reopens_a_withdrawn_relation_to_pending(
        self, make_uow, make_establishment
    ):
        """A field worker who withdrew their own access to this establishment
        gets another chance at admin review instead of staying withdrawn."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        existing = make_establishment()
        relation = MagicMock(status=UserEstablishmentStatus.WITHDRAWN)
        uow = make_uow(
            request=request,
            existing_establishment=existing,
            existing_relation=relation,
        )
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        uow.user_establishment_repo.update_status_for_ids.assert_called_once_with(
            user_id, [existing.id], UserEstablishmentStatus.PENDING
        )
        uow.user_establishment_repo.preset_relation.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        [UserEstablishmentStatus.APPROVED, UserEstablishmentStatus.PENDING],
    )
    async def test_leaves_an_approved_or_pending_relation_untouched(
        self, make_uow, make_establishment, status
    ):
        """Access that's already approved or pending isn't reset just
        because the requester's creation request got approved again."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        existing = make_establishment()
        relation = MagicMock(status=status)
        uow = make_uow(
            request=request,
            existing_establishment=existing,
            existing_relation=relation,
        )
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()

    async def test_sets_request_status_to_approved(self, make_uow, make_establishment):
        """Flips the request status once approval succeeds."""
        request = _make_request_orm(uuid.uuid4())
        uow = make_uow(request=request, existing_establishment=make_establishment())
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=uuid.uuid4()
        )

        assert request.status == EstablishmentRequestStatus.APPROVED
        uow.commit.assert_called_once()

    async def test_sets_reviewed_by_on_approval(self, make_uow, make_establishment):
        """Records which admin approved the request."""
        request = _make_request_orm(uuid.uuid4())
        reviewer_id = uuid.uuid4()
        uow = make_uow(request=request, existing_establishment=make_establishment())
        service = EstablishmentService(uow=uow)

        await service.approve_creation_request(
            request.id, _make_request(), reviewer_id=reviewer_id
        )

        assert request.reviewed_by == reviewer_id

    async def test_sends_establishment_created_email(
        self, make_uow, make_establishment
    ):
        """Notifies the requester by email with the resolved establishment's
        name, using their address on file rather than the request payload."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id)
        requester = _make_requester(id=user_id, email="worker@test.com")
        existing = make_establishment(name="Centro A")
        uow = make_uow(
            request=request, existing_establishment=existing, requester=requester
        )
        service = EstablishmentService(uow=uow)

        with patch(
            "app.services.establishments.establishment_service.send_establishment_created_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.approve_creation_request(
                request.id, _make_request(), reviewer_id=uuid.uuid4()
            )

        mock_email.assert_awaited_once_with("worker@test.com", "Centro A")


class TestRejectCreationRequest:
    @pytest.fixture
    def make_uow(self, make_request_review_uow):
        return make_request_review_uow

    async def test_raises_when_request_not_found(self, make_uow):
        """Raises EstablishmentRequestNotFoundError when the repo returns None."""
        uow = make_uow(request=None)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentRequestNotFoundError):
            await service.reject_creation_request(
                uuid.uuid4(), reviewer_id=uuid.uuid4()
            )

    async def test_raises_when_already_reviewed(self, make_uow):
        """Raises EstablishmentRequestAlreadyReviewedError when the request
        is not pending."""
        request = _make_request_orm(
            uuid.uuid4(), status=EstablishmentRequestStatus.REJECTED
        )
        uow = make_uow(request=request)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentRequestAlreadyReviewedError):
            await service.reject_creation_request(request.id, reviewer_id=uuid.uuid4())

    async def test_sets_request_status_to_rejected(self, make_uow):
        """Flips the request status and commits, without touching any
        establishment or access relation."""
        request = _make_request_orm(uuid.uuid4())
        uow = make_uow(request=request)
        service = EstablishmentService(uow=uow)

        await service.reject_creation_request(request.id, reviewer_id=uuid.uuid4())

        assert request.status == EstablishmentRequestStatus.REJECTED
        uow.commit.assert_called_once()
        uow.establishment_repo.create.assert_not_called()
        uow.user_establishment_repo.preset_relation.assert_not_called()
        uow.user_establishment_repo.update_status_for_ids.assert_not_called()

    async def test_sets_reviewed_by_on_rejection(self, make_uow):
        """Records which admin rejected the request."""
        request = _make_request_orm(uuid.uuid4())
        reviewer_id = uuid.uuid4()
        uow = make_uow(request=request)
        service = EstablishmentService(uow=uow)

        await service.reject_creation_request(request.id, reviewer_id=reviewer_id)

        assert request.reviewed_by == reviewer_id

    async def test_sends_denial_email_with_reason(self, make_uow):
        """Forwards the admin's reason through to the denial email."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id, name="Comedor Esperanza")
        requester = _make_requester(id=user_id, email="worker@test.com")
        uow = make_uow(request=request, requester=requester)
        service = EstablishmentService(uow=uow)

        with patch(
            "app.services.establishments.establishment_service.send_creation_denied_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.reject_creation_request(
                request.id, reviewer_id=uuid.uuid4(), reason="Datos incompletos"
            )

        mock_email.assert_awaited_once_with(
            "worker@test.com", "Comedor Esperanza", "Datos incompletos"
        )

    async def test_sends_denial_email_without_reason(self, make_uow):
        """The reason defaults to None when the admin doesn't provide one."""
        user_id = uuid.uuid4()
        request = _make_request_orm(user_id, name="Comedor Esperanza")
        requester = _make_requester(id=user_id, email="worker@test.com")
        uow = make_uow(request=request, requester=requester)
        service = EstablishmentService(uow=uow)

        with patch(
            "app.services.establishments.establishment_service.send_creation_denied_email",
            new_callable=AsyncMock,
        ) as mock_email:
            await service.reject_creation_request(request.id, reviewer_id=uuid.uuid4())

        mock_email.assert_awaited_once_with(
            "worker@test.com", "Comedor Esperanza", None
        )
