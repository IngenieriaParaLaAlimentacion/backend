import uuid
from unittest.mock import AsyncMock

import pytest

from app.config.settings import settings
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    EstablishmentNotFoundError,
    ImageTooLargeError,
    UnsupportedImageTypeError,
)
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

pytestmark = pytest.mark.asyncio

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def admin_actor() -> UserActor:
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.fixture
def field_worker_actor() -> UserActor:
    return UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)


@pytest.fixture
def uow(stub_establishment_lookup):
    """A mocked UoW whose establishment exists and whose relations are approved
    unless a test overrides them."""
    _uow = AsyncMock()
    stub_establishment_lookup(_uow, establishment=object())
    _uow.user_establishment_repo.get_relation = AsyncMock(return_value=None)
    return _uow


@pytest.fixture
def storage():
    """A mocked IObjectStorage; not yet exercised by the service under test."""
    return AsyncMock()


class TestImageValidation:
    async def test_accepted_image_returns_an_empty_proposal(
        self, uow, storage, admin_actor
    ):
        establishment_id = uuid.uuid4()

        proposal = await ReceiptIntakeService(uow, storage).propose_from_photo(
            establishment_id=establishment_id,
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert proposal.establishment_id == establishment_id
        assert proposal.lines == []
        assert proposal.message  # manual-fallback hint while there is no extractor

    async def test_unsupported_type_is_rejected_before_any_db_access(
        self, uow, storage, admin_actor
    ):
        with pytest.raises(UnsupportedImageTypeError):
            await ReceiptIntakeService(uow, storage).propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="application/pdf",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        uow.establishment_repo.get_by_id_or_raise.assert_not_called()

    async def test_missing_content_type_is_rejected(self, uow, storage, admin_actor):
        with pytest.raises(UnsupportedImageTypeError):
            await ReceiptIntakeService(uow, storage).propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type=None,
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_oversized_image_is_rejected(
        self, uow, storage, admin_actor, monkeypatch
    ):
        monkeypatch.setattr(settings, "receipt_image_max_bytes", 8)

        with pytest.raises(ImageTooLargeError):
            await ReceiptIntakeService(uow, storage).propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )


class TestEstablishmentChecks:
    async def test_unknown_establishment_raises(
        self, stub_establishment_lookup, admin_actor
    ):
        _uow = AsyncMock()
        stub_establishment_lookup(_uow, establishment=None)

        with pytest.raises(EstablishmentNotFoundError):
            await ReceiptIntakeService(_uow, AsyncMock()).propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_field_worker_without_approved_access_raises(
        self, uow, storage, field_worker_actor
    ):
        with pytest.raises(EstablishmentAccessDeniedError):
            await ReceiptIntakeService(uow, storage).propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=field_worker_actor,
            )
