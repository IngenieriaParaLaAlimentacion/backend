import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.settings import settings
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    EstablishmentNotFoundError,
    ImageTooLargeError,
    ObjectStorageError,
    ReceiptPhotoStorageError,
    UnsupportedImageTypeError,
)
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodLineRequest,
)
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

pytestmark = pytest.mark.asyncio

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _intake_request(**overrides) -> FoodIntakeRequest:
    fields = {
        "id": None,
        "establishment_id": uuid.uuid4(),
        "received_at": datetime.now(timezone.utc),
        "items": [FoodLineRequest(food_id=uuid.uuid4(), quantity=Decimal("1"))],
        **overrides,
    }
    return FoodIntakeRequest(**fields)


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


@pytest.fixture
def food_intake_service():
    """A mocked FoodIntakeService, exercised only by confirm_from_photo."""
    return AsyncMock()


class TestImageValidation:
    async def test_accepted_image_returns_an_empty_proposal(
        self, uow, storage, food_intake_service, admin_actor
    ):
        establishment_id = uuid.uuid4()

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        proposal = await service.propose_from_photo(
            establishment_id=establishment_id,
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert proposal.establishment_id == establishment_id
        assert proposal.lines == []
        assert proposal.message  # manual-fallback hint while there is no extractor
        storage.save.assert_not_called()  # nothing is stored until confirmation

    async def test_unsupported_type_is_rejected_before_any_db_access(
        self, uow, storage, food_intake_service, admin_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(UnsupportedImageTypeError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="application/pdf",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        uow.establishment_repo.get_by_id_or_raise.assert_not_called()

    async def test_missing_content_type_is_rejected(
        self, uow, storage, food_intake_service, admin_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(UnsupportedImageTypeError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type=None,
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_oversized_image_is_rejected(
        self, uow, storage, food_intake_service, admin_actor, monkeypatch
    ):
        monkeypatch.setattr(settings, "receipt_image_max_bytes", 8)

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(ImageTooLargeError):
            await service.propose_from_photo(
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

        service = ReceiptIntakeService(_uow, AsyncMock(), AsyncMock())
        with pytest.raises(EstablishmentNotFoundError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_field_worker_without_approved_access_raises(
        self, uow, storage, food_intake_service, field_worker_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(EstablishmentAccessDeniedError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=field_worker_actor,
            )


class TestConfirmFromPhoto:
    """Every check that would make registration fail must run before the
    photo is uploaded, so a rejected confirm never leaves an orphan in R2."""

    async def test_happy_path_saves_photo_then_registers(
        self, uow, storage, food_intake_service, admin_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        registered = object()
        food_intake_service.register = AsyncMock(return_value=(registered, True))
        data = _intake_request()

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        result = await service.confirm_from_photo(
            data=data,
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert result == (registered, True)
        storage.save.assert_awaited_once()
        saved_key = storage.save.await_args.kwargs["key"]
        assert saved_key.startswith(f"food-intake-receipts/{data.establishment_id}/")
        food_intake_service.register.assert_awaited_once_with(
            data, admin_actor, photo_key=saved_key
        )

    async def test_replay_of_an_existing_id_never_touches_storage(
        self, uow, storage, food_intake_service, admin_actor
    ):
        """A retried confirm (same client id) must not upload a second, now
        orphaned, copy of the photo."""
        existing = MagicMock()
        existing.items = []  # FoodIntakeDomain.from_db iterates this
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=existing)
        data = _intake_request(id=uuid.uuid4())

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        result = await service.confirm_from_photo(
            data=data,
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert result[1] is False
        storage.save.assert_not_called()
        food_intake_service.register.assert_not_called()

    async def test_unknown_establishment_is_rejected_before_upload(
        self, stub_establishment_lookup, storage, food_intake_service, admin_actor
    ):
        _uow = AsyncMock()
        _uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        stub_establishment_lookup(_uow, establishment=None)

        service = ReceiptIntakeService(_uow, storage, food_intake_service)
        with pytest.raises(EstablishmentNotFoundError):
            await service.confirm_from_photo(
                data=_intake_request(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        storage.save.assert_not_called()
        food_intake_service.register.assert_not_called()

    async def test_access_denied_is_rejected_before_upload(
        self, uow, storage, food_intake_service, field_worker_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(EstablishmentAccessDeniedError):
            await service.confirm_from_photo(
                data=_intake_request(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=field_worker_actor,
            )

        storage.save.assert_not_called()
        food_intake_service.register.assert_not_called()

    async def test_storage_failure_is_translated_and_skips_register(
        self, uow, storage, food_intake_service, admin_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        storage.save.side_effect = ObjectStorageError("some-key", "connection reset")

        service = ReceiptIntakeService(uow, storage, food_intake_service)
        with pytest.raises(ReceiptPhotoStorageError):
            await service.confirm_from_photo(
                data=_intake_request(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        food_intake_service.register.assert_not_called()
