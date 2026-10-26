import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.settings import settings
from app.domain.food_catalog import MeasurementUnit
from app.domain.food_intake import FoodIntakeOriginType
from app.domain.unit_conversion import ConversionFactors
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentAccessDeniedError,
    EstablishmentNotFoundError,
    ImageContentMismatchError,
    ImageTooLargeError,
    LlmClientError,
    ObjectStorageError,
    ReceiptPhotoStorageError,
    UnsupportedImageTypeError,
)
from app.schemas.food_intakes.food_intake_schema import (
    FoodIntakeRequest,
    FoodLineRequest,
)
from app.services.food_intakes.receipt_intake_service import ReceiptIntakeService

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _intake_request(**overrides) -> FoodIntakeRequest:
    fields = {
        "id": None,
        "establishment_id": uuid.uuid4(),
        "occurred_at": datetime.now(timezone.utc),
        "origin_type": FoodIntakeOriginType.OTHER,
        "is_recurring": False,
        "items": [FoodLineRequest(food_id=uuid.uuid4(), quantity=Decimal("1"))],
        **overrides,
    }
    return FoodIntakeRequest(**fields)


def _factors_for_every_food(factors: ConversionFactors) -> AsyncMock:
    """A factors lookup that, like the repository, answers for every food asked."""
    return AsyncMock(side_effect=lambda food_ids: dict.fromkeys(food_ids, factors))


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
    _uow.food_repo.find_best_match = AsyncMock(return_value=None)
    _uow.food_equivalence_repo.get_factors_by_food_ids = _factors_for_every_food(
        ConversionFactors()
    )
    return _uow


@pytest.fixture
def storage():
    """A mocked IObjectStorage."""
    return AsyncMock()


@pytest.fixture
def food_intake_service():
    """A mocked FoodIntakeService, exercised only by confirm_from_photo."""
    return AsyncMock()


@pytest.fixture
def llm_client():
    """A mocked ILlmClient defaulting to an empty extraction result."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value={"lines": []})
    return client


class TestImageValidation:
    async def test_unsupported_type_is_rejected_before_any_db_access(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(UnsupportedImageTypeError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="application/pdf",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        uow.establishment_repo.get_by_id_or_raise.assert_not_called()

    async def test_missing_content_type_is_rejected(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(UnsupportedImageTypeError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type=None,
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_oversized_image_is_rejected(
        self, uow, storage, food_intake_service, llm_client, admin_actor, monkeypatch
    ):
        monkeypatch.setattr(settings, "receipt_image_max_bytes", 8)

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(ImageTooLargeError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_content_not_matching_declared_type_is_rejected(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        """An allow-listed content type whose bytes don't back it up -- e.g. a
        mislabeled upload or a spoofed header -- is rejected before any DB
        access, same as an unsupported type."""
        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(ImageContentMismatchError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=b"not actually a png",
                actor=admin_actor,
            )

        uow.establishment_repo.get_by_id_or_raise.assert_not_called()


class TestEstablishmentChecks:
    async def test_unknown_establishment_raises(
        self, stub_establishment_lookup, admin_actor
    ):
        _uow = AsyncMock()
        stub_establishment_lookup(_uow, establishment=None)

        service = ReceiptIntakeService(_uow, AsyncMock(), AsyncMock(), AsyncMock())
        with pytest.raises(EstablishmentNotFoundError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

    async def test_field_worker_without_approved_access_raises(
        self, uow, storage, food_intake_service, llm_client, field_worker_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(EstablishmentAccessDeniedError):
            await service.propose_from_photo(
                establishment_id=uuid.uuid4(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=field_worker_actor,
            )


class TestExtraction:
    """propose_from_photo's LLM-backed extraction step."""

    async def test_extracted_lines_are_returned_needing_review(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [{"description": "Arroz 1kg"}, {"description": "Leche 1L"}]
            }
        )
        establishment_id = uuid.uuid4()

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=establishment_id,
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert proposal.establishment_id == establishment_id
        assert [line.description for line in proposal.lines] == [
            "Arroz 1kg",
            "Leche 1L",
        ]
        assert all(line.food is None for line in proposal.lines)
        assert proposal.message is None
        storage.save.assert_not_called()  # nothing is stored until confirmation

    async def test_extracted_quantity_and_unit_text_are_returned_when_present(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [
                    {
                        "description": "Arroz 1kg",
                        "raw_quantity": 1,
                        "raw_unit_text": "kg",
                    },
                    {
                        "description": "Yerba",
                        "raw_quantity": None,
                        "raw_unit_text": None,
                    },
                ]
            }
        )

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        rice, yerba = proposal.lines
        assert rice.raw_quantity == Decimal("1")
        assert rice.raw_unit_text == "kg"
        assert yerba.raw_quantity is None
        assert yerba.raw_unit_text is None

    async def test_unusable_quantity_is_dropped_without_losing_the_other_lines(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [
                    # a barcode read as the quantity does not fit a proposed line
                    {
                        "description": "Fideos",
                        "raw_quantity": 7791234567890,
                        "raw_unit_text": "un",
                    },
                    {
                        "description": "Arroz 1kg",
                        "raw_quantity": "1,5",
                        "raw_unit_text": "kg",
                    },
                ]
            }
        )

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        noodles, rice = proposal.lines
        assert noodles.raw_quantity is None
        assert rice.raw_quantity == Decimal("1.5")

    async def test_confident_catalog_match_populates_food(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        matched_food = SimpleNamespace(
            id=uuid.uuid4(), name="Arroz", base_unit=MeasurementUnit.KILOGRAMOS
        )
        uow.food_repo.find_best_match = AsyncMock(return_value=matched_food)
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [
                    {
                        "description": "Arroz 1kg",
                        "raw_quantity": None,
                        "raw_unit_text": None,
                    }
                ]
            }
        )

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        (line,) = proposal.lines
        assert line.food is not None
        assert line.food.id == matched_food.id
        assert line.food.name == "Arroz"
        uow.food_repo.find_best_match.assert_awaited_once_with(
            "Arroz 1kg",
            settings.receipt_food_match_min_word_similarity,
            settings.receipt_food_match_min_similarity,
        )

    @pytest.mark.parametrize(
        ("base_unit", "factors", "raw_quantity", "raw_unit_text", "quantity", "unit"),
        [
            # printed in the food's own base unit
            (
                MeasurementUnit.KILOGRAMOS,
                ConversionFactors(),
                1,
                "kg",
                Decimal("1"),
                "kilogramos",
            ),
            # printed in another unit of the same dimension
            (
                MeasurementUnit.KILOGRAMOS,
                ConversionFactors(),
                500,
                "g",
                Decimal("0.5"),
                "kilogramos",
            ),
            # a different dimension, through the food's stored unit weight
            (
                MeasurementUnit.UNIDADES,
                ConversionFactors(unit_weight_g=Decimal("50")),
                600,
                "g",
                Decimal("12"),
                "unidades",
            ),
            # a different dimension, with no factor stored for the food
            (MeasurementUnit.UNIDADES, ConversionFactors(), 1, "kg", None, None),
        ],
    )
    async def test_matched_line_is_prefilled_in_base_unit_when_convertible(
        self,
        uow,
        storage,
        food_intake_service,
        llm_client,
        admin_actor,
        base_unit,
        factors,
        raw_quantity,
        raw_unit_text,
        quantity,
        unit,
    ):
        uow.food_repo.find_best_match = AsyncMock(
            return_value=SimpleNamespace(
                id=uuid.uuid4(), name="Arroz", base_unit=base_unit
            )
        )
        uow.food_equivalence_repo.get_factors_by_food_ids = _factors_for_every_food(
            factors
        )
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [
                    {
                        "description": "Arroz",
                        "raw_quantity": raw_quantity,
                        "raw_unit_text": raw_unit_text,
                    }
                ]
            }
        )

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        (line,) = proposal.lines
        assert line.quantity == quantity
        assert line.unit == unit
        # the printed values are passed through whether or not they were used
        assert line.raw_quantity == Decimal(raw_quantity)
        assert line.raw_unit_text == raw_unit_text

    async def test_unmatched_line_has_no_quantity_or_unit(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        llm_client.complete = AsyncMock(
            return_value={
                "lines": [
                    {
                        "description": "Cosa rara 1kg",
                        "raw_quantity": 1,
                        "raw_unit_text": "kg",
                    }
                ]
            }
        )

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        (line,) = proposal.lines
        assert line.food is None
        assert line.quantity is None
        assert line.unit is None

    async def test_no_lines_detected_returns_manual_fallback_message(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert proposal.lines == []
        assert proposal.message

    async def test_llm_failure_falls_back_to_manual_message(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        llm_client.complete = AsyncMock(side_effect=LlmClientError("gemini is down"))

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        proposal = await service.propose_from_photo(
            establishment_id=uuid.uuid4(),
            content_type="image/png",
            image=PNG_BYTES,
            actor=admin_actor,
        )

        assert proposal.lines == []
        assert proposal.message


class TestConfirmFromPhoto:
    """Every check that would make registration fail must run before the
    photo is uploaded, so a rejected confirm never leaves an orphan in R2."""

    async def test_happy_path_saves_photo_then_registers(
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        registered = object()
        food_intake_service.register = AsyncMock(return_value=(registered, True))
        data = _intake_request()

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
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
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        """A retried confirm (same client id) must not upload a second, now
        orphaned, copy of the photo."""
        existing = MagicMock()
        existing.items = []  # FoodIntakeDomain.from_db iterates this
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=existing)
        data = _intake_request(id=uuid.uuid4())

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
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
        self,
        stub_establishment_lookup,
        storage,
        food_intake_service,
        llm_client,
        admin_actor,
    ):
        _uow = AsyncMock()
        _uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        stub_establishment_lookup(_uow, establishment=None)

        service = ReceiptIntakeService(_uow, storage, food_intake_service, llm_client)
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
        self, uow, storage, food_intake_service, llm_client, field_worker_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
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
        self, uow, storage, food_intake_service, llm_client, admin_actor
    ):
        uow.food_intake_repo.get_by_id = AsyncMock(return_value=None)
        storage.save.side_effect = ObjectStorageError("some-key", "connection reset")

        service = ReceiptIntakeService(uow, storage, food_intake_service, llm_client)
        with pytest.raises(ReceiptPhotoStorageError):
            await service.confirm_from_photo(
                data=_intake_request(),
                content_type="image/png",
                image=PNG_BYTES,
                actor=admin_actor,
            )

        food_intake_service.register.assert_not_called()
