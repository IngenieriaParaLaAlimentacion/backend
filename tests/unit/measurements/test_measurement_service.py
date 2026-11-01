import uuid
from datetime import date, datetime, timezone
from math import ceil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.establishment import UserEstablishmentStatus
from app.domain.measurement import (
    AlertSeverity,
    AlertType,
    EvolutionOrder,
    MeasurementDomain,
    MeasurementListingParams,
    MeasurementListItemDomain,
)
from app.domain.pagination import PaginatedResult
from app.domain.subject import Sex
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.schemas.measurements.measurement_schema import MeasurementRequest
from app.services.measurements.measurement_service import MeasurementService
from tests.unit.conftest import aiter_of, capturing_exporter, drain


@pytest.fixture
def make_subject():
    def _make(sex: Sex = Sex.MALE, birth_date: date = date(2000, 1, 1)):
        s = MagicMock()
        s.id = uuid.uuid4()
        s.sex = sex
        s.birth_date = birth_date
        return s

    return _make


@pytest.fixture
def make_measurement():
    def _make():
        m = MagicMock()
        m.id = uuid.uuid4()
        m.subject_id = uuid.uuid4()
        m.responsible_id = uuid.uuid4()
        m.establishment_id = uuid.uuid4()
        m.weight_kg = 70.0
        m.height_cm = 170.0
        m.bmi = 70.0 / (1.70**2)
        m.measured_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        m.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        m.alerts = []
        m.observation = None
        return m

    return _make


@pytest.fixture
def make_uow(make_subject, make_measurement, stub_establishment_lookup):
    def _make(
        subject=None,
        establishment=MagicMock(),
        relation=None,
        measurement=None,
    ):
        uow = AsyncMock()
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject or make_subject())
        stub_establishment_lookup(uow, establishment)
        uow.user_establishment_repo.get_relation = AsyncMock(return_value=relation)
        uow.measurement_repo.get_by_id = AsyncMock(return_value=None)
        uow.measurement_repo.create = AsyncMock(
            return_value=measurement or make_measurement()
        )
        uow.measurement_alert_repo.create_bulk = AsyncMock()
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def valid_request():
    return MeasurementRequest(
        subject_id=uuid.uuid4(),
        establishment_id=uuid.uuid4(),
        weight_kg=70.0,
        height_cm=170.0,
        measured_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def admin_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


@pytest.fixture
def field_worker_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.FIELD_WORKER)


class TestRegisterValidation:
    async def test_raises_if_subject_not_found(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(subject=None)
        uow.subject_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(SubjectNotFoundError):
            await MeasurementService(uow).register(valid_request, admin_actor)

        uow.commit.assert_not_called()

    async def test_raises_if_establishment_not_found(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(establishment=None)

        with pytest.raises(EstablishmentNotFoundError):
            await MeasurementService(uow).register(valid_request, admin_actor)

        uow.commit.assert_not_called()


class TestEstablishmentAccessCheck:
    async def test_field_worker_with_no_relation_is_forbidden(
        self, make_uow, valid_request, field_worker_actor
    ):
        uow = make_uow(relation=None)

        with pytest.raises(ForbiddenError):
            await MeasurementService(uow).register(valid_request, field_worker_actor)

        uow.commit.assert_not_called()

    async def test_field_worker_with_pending_relation_is_forbidden(
        self, make_uow, valid_request, field_worker_actor
    ):
        relation = MagicMock()
        relation.status = UserEstablishmentStatus.PENDING
        uow = make_uow(relation=relation)

        with pytest.raises(ForbiddenError):
            await MeasurementService(uow).register(valid_request, field_worker_actor)

    async def test_field_worker_with_approved_relation_succeeds(
        self, make_uow, valid_request, field_worker_actor
    ):
        relation = MagicMock()
        relation.status = UserEstablishmentStatus.APPROVED
        uow = make_uow(relation=relation)

        result, created = await MeasurementService(uow).register(
            valid_request, field_worker_actor
        )

        assert created is True
        assert isinstance(result, MeasurementDomain)

    async def test_admin_skips_establishment_check(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(relation=None)

        result, created = await MeasurementService(uow).register(
            valid_request, admin_actor
        )

        uow.user_establishment_repo.get_relation.assert_not_called()
        assert created is True
        assert isinstance(result, MeasurementDomain)


class TestRegisterPersistence:
    async def test_new_measurement_with_alerts_calls_create_bulk(
        self, make_uow, make_subject, make_measurement, valid_request, admin_actor
    ):
        subject = make_subject(sex=Sex.MALE, birth_date=date(2000, 1, 1))
        measurement = make_measurement()
        uow = make_uow(subject=subject, measurement=measurement)

        raw_alerts = [(AlertType.OVERWEIGHT, AlertSeverity.MEDIUM, "detail")]
        with patch(
            "app.services.measurements.measurement_service.evaluate_alerts",
            return_value=raw_alerts,
        ):
            await MeasurementService(uow).register(valid_request, admin_actor)

        uow.measurement_alert_repo.create_bulk.assert_called_once_with(
            measurement.id, raw_alerts
        )

    async def test_new_measurement_without_alerts_skips_create_bulk(
        self, make_uow, make_subject, make_measurement, valid_request, admin_actor
    ):
        subject = make_subject(sex=Sex.MALE, birth_date=date(2000, 1, 1))
        measurement = make_measurement()
        uow = make_uow(subject=subject, measurement=measurement)

        with patch(
            "app.services.measurements.measurement_service.evaluate_alerts",
            return_value=[],
        ):
            await MeasurementService(uow).register(valid_request, admin_actor)

        uow.measurement_alert_repo.create_bulk.assert_not_called()

    async def test_commits_after_create(self, make_uow, valid_request, admin_actor):
        uow = make_uow()
        await MeasurementService(uow).register(valid_request, admin_actor)
        uow.commit.assert_called_once()

    async def test_replay_by_id_returns_existing_without_create(
        self, make_uow, make_measurement, valid_request, admin_actor
    ):
        """A request whose id already exists replays the stored measurement (200)."""
        existing = make_measurement()
        request = valid_request.model_copy(update={"id": existing.id})
        uow = make_uow()
        uow.measurement_repo.get_by_id = AsyncMock(return_value=existing)

        result, created = await MeasurementService(uow).register(request, admin_actor)

        assert created is False
        assert result.id == existing.id
        uow.measurement_repo.create.assert_not_called()
        uow.measurement_alert_repo.create_bulk.assert_not_called()
        uow.commit.assert_not_called()

    async def test_id_race_on_conflict_replays_existing(
        self, make_uow, make_measurement, valid_request, admin_actor
    ):
        """A concurrent insert of the same id surfaces as a replay, not a conflict."""
        raced = make_measurement()
        request = valid_request.model_copy(update={"id": raced.id})
        uow = make_uow()
        # First pre-check misses; the row lands between the check and our insert.
        uow.measurement_repo.get_by_id = AsyncMock(side_effect=[None, raced])
        uow.measurement_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("id", raced.id)
        )

        result, created = await MeasurementService(uow).register(request, admin_actor)

        assert created is False
        assert result.id == raced.id
        uow.measurement_alert_repo.create_bulk.assert_not_called()
        uow.commit.assert_not_called()


@pytest.fixture
def make_listing_measurement(make_measurement):
    """An ORM-like measurement with subject/establishment/responsible loaded."""

    def _make():
        m = make_measurement()
        subject = MagicMock()
        subject.id = uuid.uuid4()
        subject.dni = 12345678
        subject.sex = Sex.FEMALE
        subject.name = "Ana"
        subject.last_name = "Perez"
        subject.birth_date = date(2020, 1, 1)
        establishment = MagicMock()
        establishment.id = uuid.uuid4()
        establishment.name = "Comedor Norte"
        establishment.city = "La Plata"
        establishment.province = "Buenos Aires"
        responsible = MagicMock()
        responsible.id = uuid.uuid4()
        responsible.name = "Juan"
        responsible.last_name = "Gomez"
        m.subject = subject
        m.establishment = establishment
        m.responsible = responsible
        return m

    return _make


class TestListMeasurements:
    @pytest.fixture
    def make_uow(self):
        def _make(measurements, total):
            uow = AsyncMock()
            uow.measurement_repo.get_measurement_listing = AsyncMock(
                return_value=(measurements, total)
            )
            return uow

        return _make

    async def test_returns_enriched_items(self, make_listing_measurement, make_uow):
        measurements = [make_listing_measurement(), make_listing_measurement()]
        uow = make_uow(measurements, total=2)

        result = await MeasurementService(uow).list_measurements(
            page=1, page_size=20, params=MeasurementListingParams()
        )

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 2
        item = result.items[0]
        assert item.subject.name == "Ana"
        assert item.establishment.city == "La Plata"
        assert item.responsible.last_name == "Gomez"

    async def test_calculates_total_pages(self, make_listing_measurement, make_uow):
        measurements = [make_listing_measurement() for _ in range(5)]
        uow = make_uow(measurements, total=23)

        result = await MeasurementService(uow).list_measurements(
            page=1, page_size=5, params=MeasurementListingParams()
        )

        assert result.total_pages == ceil(23 / 5)

    async def test_passes_correct_offset(self, make_uow):
        uow = make_uow([], total=0)
        params = MeasurementListingParams()

        await MeasurementService(uow).list_measurements(
            page=3, page_size=10, params=params
        )

        uow.measurement_repo.get_measurement_listing.assert_called_once_with(
            limit=10, offset=20, params=params
        )


class TestGetSubjectEvolution:
    async def test_raises_when_subject_missing(self, make_uow):
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(SubjectNotFoundError):
            await MeasurementService(uow).get_subject_evolution(uuid.uuid4())

    async def test_returns_points_in_repo_order(
        self, make_uow, make_subject, make_measurement
    ):
        subject = make_subject()
        early = make_measurement()
        early.measured_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        late = make_measurement()
        late.measured_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        uow = make_uow(subject=subject)
        uow.measurement_repo.get_subject_evolution = AsyncMock(
            return_value=[early, late]
        )

        result = await MeasurementService(uow).get_subject_evolution(subject.id)

        assert result.subject.id == subject.id
        assert [p.measured_at for p in result.points] == [
            early.measured_at,
            late.measured_at,
        ]

    async def test_defaults_to_oldest_first(self, make_uow, make_subject):
        subject = make_subject()
        uow = make_uow(subject=subject)
        uow.measurement_repo.get_subject_evolution = AsyncMock(return_value=[])

        await MeasurementService(uow).get_subject_evolution(subject.id)

        uow.measurement_repo.get_subject_evolution.assert_called_once_with(
            subject.id, order=EvolutionOrder.OLDEST_FIRST
        )

    async def test_passes_requested_order_to_repo(self, make_uow, make_subject):
        subject = make_subject()
        uow = make_uow(subject=subject)
        uow.measurement_repo.get_subject_evolution = AsyncMock(return_value=[])

        await MeasurementService(uow).get_subject_evolution(
            subject.id, order=EvolutionOrder.NEWEST_FIRST
        )

        uow.measurement_repo.get_subject_evolution.assert_called_once_with(
            subject.id, order=EvolutionOrder.NEWEST_FIRST
        )


class TestExportMeasurementListing:
    async def test_streams_the_whole_filtered_set(self, make_listing_measurement):
        uow = AsyncMock()
        uow.measurement_repo.stream_for_export = MagicMock(
            return_value=aiter_of([make_listing_measurement()])
        )
        seen: list = []
        params = MeasurementListingParams(city="Rosario")

        data = await drain(
            MeasurementService(uow).export_measurement_listing(
                params, capturing_exporter(seen)
            )
        )

        assert data == b"row"
        uow.measurement_repo.stream_for_export.assert_called_once_with(params)

    async def test_rows_are_mapped_to_listing_domain_objects(
        self, make_listing_measurement
    ):
        uow = AsyncMock()
        uow.measurement_repo.stream_for_export = MagicMock(
            return_value=aiter_of(
                [make_listing_measurement(), make_listing_measurement()]
            )
        )
        seen: list = []

        await drain(
            MeasurementService(uow).export_measurement_listing(
                MeasurementListingParams(), capturing_exporter(seen)
            )
        )

        assert len(seen) == 2
        assert all(isinstance(m, MeasurementListItemDomain) for m in seen)

    async def test_empty_result_still_reaches_the_exporter(self):
        uow = AsyncMock()
        uow.measurement_repo.stream_for_export = MagicMock(return_value=aiter_of([]))
        seen: list = []

        data = await drain(
            MeasurementService(uow).export_measurement_listing(
                MeasurementListingParams(), capturing_exporter(seen)
            )
        )

        assert data == b""
        assert seen == []

    async def test_count_uses_the_listing_filters(self):
        uow = AsyncMock()
        uow.measurement_repo.count_for_export = AsyncMock(return_value=42)
        params = MeasurementListingParams(city="Rosario")

        assert await MeasurementService(uow).count_measurement_export(params) == 42
        uow.measurement_repo.count_for_export.assert_awaited_once_with(params)


async def test_register_persists_optional_observation(
    make_uow, valid_request, admin_actor, make_measurement
):
    measurement = make_measurement()
    measurement.observation = "Sin calzado."
    uow = make_uow(measurement=measurement)
    data = valid_request.model_copy(update={"observation": "Sin calzado."})

    result, created = await MeasurementService(uow).register(data, admin_actor)

    assert created is True
    assert result.observation == "Sin calzado."
    assert uow.measurement_repo.create.call_args.kwargs["observation"] == "Sin calzado."


async def test_replay_does_not_replace_original_observation(
    make_uow, valid_request, admin_actor, make_measurement
):
    original = make_measurement()
    original.observation = "Original"
    uow = make_uow()
    uow.measurement_repo.get_by_id.return_value = original
    data = valid_request.model_copy(
        update={"id": original.id, "observation": "Changed"}
    )

    result, created = await MeasurementService(uow).register(data, admin_actor)

    assert created is False
    assert result.observation == "Original"
    uow.measurement_repo.create.assert_not_called()
