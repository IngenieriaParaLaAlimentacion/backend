import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment_dashboard import (
    EstablishmentSubjectListingParams,
    NutritionalStatus,
)
from app.domain.measurement import AlertSeverity, AlertType
from app.domain.subject import Sex
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.services.establishments.establishment_dashboard_service import (
    EstablishmentDashboardService,
)
from tests.unit.conftest import aiter_of, capturing_exporter, drain

_ADMIN = UserActor(user_id=uuid.uuid4(), role=UserRole.ADMIN)


def _row(alert_type: AlertType | None, count: int) -> SimpleNamespace:
    """A row as returned by DashboardRepository.get_status_distribution."""
    severity = None if alert_type is None else AlertSeverity.HIGH
    return SimpleNamespace(alert_type=alert_type, severity=severity, count=count)


def _metrics_row(subject_count: int) -> SimpleNamespace:
    """A row as returned by DashboardRepository.get_metrics."""
    if subject_count == 0:
        return SimpleNamespace(
            subject_count=0,
            last_measured_at=None,
            avg_height_cm=None,
            avg_weight_kg=None,
            avg_bmi=None,
            avg_age_months=None,
        )
    return SimpleNamespace(
        subject_count=subject_count,
        last_measured_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        avg_height_cm=118.456,
        avg_weight_kg=21.234,
        avg_bmi=15.6789,
        avg_age_months=77.4,
    )


@pytest.fixture
def establishment(make_establishment):
    return make_establishment()


@pytest.fixture
def make_dashboard_uow(establishment, stub_establishment_lookup):
    """Build an AsyncMock UnitOfWork wired for the dashboard repository."""

    def _make(
        metrics_row=None,
        distribution=None,
        measurement_count=0,
        subject_rows=None,
        subject_total=0,
        movement_dates=None,
        found=True,
    ):
        uow = AsyncMock()
        stub_establishment_lookup(uow, establishment if found else None)
        uow.establishment_dashboard_repo.get_metrics = AsyncMock(
            return_value=metrics_row if metrics_row is not None else _metrics_row(0)
        )
        uow.establishment_dashboard_repo.get_last_movement_dates = AsyncMock(
            return_value=movement_dates
            if movement_dates is not None
            else SimpleNamespace(last_intake_at=None, last_outflow_at=None)
        )
        uow.establishment_dashboard_repo.count_measurements = AsyncMock(
            return_value=measurement_count
        )
        uow.establishment_dashboard_repo.get_status_distribution = AsyncMock(
            return_value=distribution or []
        )
        uow.establishment_dashboard_repo.get_subject_listing = AsyncMock(
            return_value=(subject_rows or [], subject_total)
        )
        return uow

    return _make


class TestAlertStatusRollup:
    def test_maps_missing_alert_to_normal(self):
        result = EstablishmentDashboardService._build_alert_status(
            [_row(None, 4)], total=4
        )
        assert result.distribution[0].status == NutritionalStatus.NORMAL
        assert result.severity is None
        assert result.at_risk_count == 0

    def test_maps_each_alert_type_to_its_status(self):
        rows = [
            _row(AlertType.WASTED, 1),
            _row(AlertType.OBESE, 1),
            _row(AlertType.SEVERELY_WASTED, 1),
            _row(AlertType.OVERWEIGHT, 1),
        ]
        result = EstablishmentDashboardService._build_alert_status(rows, total=4)
        assert {e.status for e in result.distribution} == {
            NutritionalStatus.WASTED,
            NutritionalStatus.OBESE,
            NutritionalStatus.SEVERELY_WASTED,
            NutritionalStatus.OVERWEIGHT,
        }

    def test_percentages_are_relative_to_the_total(self):
        rows = [_row(None, 3), _row(AlertType.WASTED, 1)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=4)
        by_status = {e.status: e for e in result.distribution}
        assert by_status[NutritionalStatus.NORMAL].percentage == 75.0
        assert by_status[NutritionalStatus.WASTED].percentage == 25.0

    def test_percentages_are_rounded_to_two_decimals(self):
        rows = [_row(None, 1), _row(AlertType.WASTED, 2)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=3)
        assert {e.percentage for e in result.distribution} == {33.33, 66.67}

    def test_severity_is_the_worst_present_not_the_most_common(self):
        rows = [_row(None, 98), _row(AlertType.SEVERELY_WASTED, 2)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=100)
        assert result.dominant_status == NutritionalStatus.NORMAL
        assert result.severity == AlertSeverity.CRITICAL

    def test_severity_is_none_when_everyone_is_normal(self):
        result = EstablishmentDashboardService._build_alert_status(
            [_row(None, 10)], total=10
        )
        assert result.severity is None

    def test_dominant_status_is_the_largest_group(self):
        rows = [_row(None, 2), _row(AlertType.WASTED, 7)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=9)
        assert result.dominant_status == NutritionalStatus.WASTED

    def test_ties_break_towards_the_more_severe_status(self):
        rows = [_row(None, 5), _row(AlertType.SEVERELY_WASTED, 5)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=10)
        assert result.dominant_status == NutritionalStatus.SEVERELY_WASTED

    def test_at_risk_excludes_normal_subjects(self):
        rows = [_row(None, 6), _row(AlertType.WASTED, 3), _row(AlertType.OBESE, 1)]
        result = EstablishmentDashboardService._build_alert_status(rows, total=10)
        assert result.at_risk_count == 4
        assert result.at_risk_percentage == 40.0

    def test_distribution_is_ordered_by_count_descending(self):
        rows = [
            _row(AlertType.WASTED, 2),
            _row(None, 7),
            _row(AlertType.OBESE, 1),
        ]
        result = EstablishmentDashboardService._build_alert_status(rows, total=10)
        assert [e.count for e in result.distribution] == [7, 2, 1]


class TestGetEstablishmentDashboard:
    pytestmark = pytest.mark.asyncio

    async def test_raises_when_establishment_is_unknown(self, make_dashboard_uow):
        service = EstablishmentDashboardService(make_dashboard_uow(found=False))
        with pytest.raises(EstablishmentNotFoundError):
            await service.get_establishment_dashboard(uuid.uuid4(), _ADMIN)

    async def test_empty_establishment_reports_no_data(self, make_dashboard_uow):
        service = EstablishmentDashboardService(
            make_dashboard_uow(metrics_row=_metrics_row(0))
        )
        result = await service.get_establishment_dashboard(uuid.uuid4(), _ADMIN)

        assert result.has_data is False
        assert result.metrics.avg_bmi is None
        assert result.metrics.avg_height_cm is None
        assert result.metrics.avg_weight_kg is None
        assert result.metrics.avg_age_months is None
        assert result.metrics.last_measured_at is None
        assert result.alert_status.severity is None
        assert result.alert_status.distribution == []

    async def test_empty_establishment_skips_the_extra_queries(
        self, make_dashboard_uow
    ):
        uow = make_dashboard_uow(metrics_row=_metrics_row(0))
        await EstablishmentDashboardService(uow).get_establishment_dashboard(
            uuid.uuid4(), _ADMIN
        )

        uow.establishment_dashboard_repo.count_measurements.assert_not_called()
        uow.establishment_dashboard_repo.get_status_distribution.assert_not_called()

    async def test_populated_establishment_rounds_its_averages(
        self, make_dashboard_uow
    ):
        uow = make_dashboard_uow(
            metrics_row=_metrics_row(3),
            distribution=[_row(None, 3)],
            measurement_count=7,
        )
        result = await EstablishmentDashboardService(uow).get_establishment_dashboard(
            uuid.uuid4(), _ADMIN
        )

        assert result.has_data is True
        assert result.metrics.subject_count == 3
        assert result.metrics.measurement_count == 7
        assert result.metrics.avg_height_cm == 118.46
        assert result.metrics.avg_weight_kg == 21.23
        assert result.metrics.avg_bmi == 15.68

    async def test_average_age_is_a_whole_number_of_months(self, make_dashboard_uow):
        uow = make_dashboard_uow(
            metrics_row=_metrics_row(3), distribution=[_row(None, 3)]
        )
        result = await EstablishmentDashboardService(uow).get_establishment_dashboard(
            uuid.uuid4(), _ADMIN
        )
        assert result.metrics.avg_age_months == 77

    async def test_includes_the_establishment_identification(
        self, make_dashboard_uow, establishment
    ):
        uow = make_dashboard_uow(metrics_row=_metrics_row(0))
        result = await EstablishmentDashboardService(uow).get_establishment_dashboard(
            uuid.uuid4(), _ADMIN
        )
        assert result.establishment.name == establishment.name
        assert result.establishment.city == establishment.city


def _alert(alert_type: AlertType) -> SimpleNamespace:
    """An ORM-like MeasurementAlert row."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        measurement_id=uuid.uuid4(),
        alert_type=alert_type,
        severity=AlertSeverity.CRITICAL,
        detail="test alert",
        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )


def _measurement(alerts, birth_date=date(2018, 1, 1)):
    """An ORM-like Measurement with a loaded subject and alert list."""
    subject = MagicMock()
    subject.id = uuid.uuid4()
    subject.dni = 30000001
    subject.name = "Bruno"
    subject.last_name = "Test"
    subject.sex = Sex.MALE
    subject.birth_date = birth_date

    measurement = MagicMock()
    measurement.id = uuid.uuid4()
    measurement.subject = subject
    measurement.alerts = alerts
    measurement.measured_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
    measurement.weight_kg = 20.0
    measurement.height_cm = 118.0
    measurement.bmi = 14.36
    return measurement


class TestSubjectItemBuilding:
    def test_subject_without_alerts_is_normal(self):
        item = EstablishmentDashboardService._build_subject_item(_measurement([]), 2)
        assert item.nutritional_status == NutritionalStatus.NORMAL
        assert item.measurement_count == 2

    def test_subject_status_comes_from_its_latest_alert(self):
        measurement = _measurement([_alert(AlertType.SEVERELY_WASTED)])
        item = EstablishmentDashboardService._build_subject_item(measurement, 1)
        assert item.nutritional_status == NutritionalStatus.SEVERELY_WASTED

    def test_age_is_computed_at_the_measurement_date(self):
        # Born 2018-01-01, measured 2024-06-01 -> 77 completed months.
        item = EstablishmentDashboardService._build_subject_item(_measurement([]), 1)
        assert item.age_months == 77

    def test_carries_the_latest_measurement(self):
        item = EstablishmentDashboardService._build_subject_item(_measurement([]), 1)
        assert item.latest_measurement.weight_kg == 20.0
        assert item.latest_measurement.height_cm == 118.0


class TestSubjectListing:
    pytestmark = pytest.mark.asyncio

    async def test_raises_when_establishment_is_unknown(self, make_dashboard_uow):
        service = EstablishmentDashboardService(make_dashboard_uow(found=False))
        with pytest.raises(EstablishmentNotFoundError):
            await service.list_establishment_subjects(
                establishment_id=uuid.uuid4(),
                page=1,
                page_size=20,
                params=EstablishmentSubjectListingParams(),
            )

    async def test_pagination_is_translated_to_an_offset(self, make_dashboard_uow):
        uow = make_dashboard_uow(subject_rows=[], subject_total=0)
        await EstablishmentDashboardService(uow).list_establishment_subjects(
            establishment_id=uuid.uuid4(),
            page=3,
            page_size=10,
            params=EstablishmentSubjectListingParams(),
        )
        _, kwargs = uow.establishment_dashboard_repo.get_subject_listing.call_args
        assert kwargs["offset"] == 20
        assert kwargs["limit"] == 10

    async def test_page_below_one_is_clamped(self, make_dashboard_uow):
        uow = make_dashboard_uow(subject_rows=[], subject_total=0)
        result = await EstablishmentDashboardService(uow).list_establishment_subjects(
            establishment_id=uuid.uuid4(),
            page=0,
            page_size=10,
            params=EstablishmentSubjectListingParams(),
        )
        _, kwargs = uow.establishment_dashboard_repo.get_subject_listing.call_args
        assert kwargs["offset"] == 0
        assert result.page == 1


class TestExportEstablishmentSubjects:
    pytestmark = pytest.mark.asyncio

    @staticmethod
    def _row(measurement_count: int = 2) -> SimpleNamespace:
        """A repo row: the subject's latest measurement plus their count here."""
        return SimpleNamespace(
            Measurement=_measurement([]), measurement_count=measurement_count
        )

    async def test_preflight_raises_before_any_streaming(self, make_dashboard_uow):
        """The 404 must land before the response starts; once bytes are on the
        wire the status is already 200 and this could only truncate the file."""
        uow = make_dashboard_uow(found=False)

        with pytest.raises(EstablishmentNotFoundError):
            await EstablishmentDashboardService(uow).prepare_establishment_export(
                uuid.uuid4(), EstablishmentSubjectListingParams()
            )

    async def test_preflight_returns_the_name_and_the_count(
        self, make_dashboard_uow, establishment
    ):
        uow = make_dashboard_uow()
        uow.establishment_dashboard_repo.count_for_export = AsyncMock(return_value=7)

        name, total = await EstablishmentDashboardService(
            uow
        ).prepare_establishment_export(
            establishment.id, EstablishmentSubjectListingParams()
        )

        assert name == establishment.name
        assert total == 7

    async def test_streams_the_whole_filtered_set(
        self, make_dashboard_uow, establishment
    ):
        uow = make_dashboard_uow()
        uow.establishment_dashboard_repo.stream_for_export = MagicMock(
            return_value=aiter_of([self._row(), self._row()])
        )
        seen: list = []
        params = EstablishmentSubjectListingParams(search="Bruno")

        data = await drain(
            EstablishmentDashboardService(uow).export_establishment_subjects(
                establishment.id, params, capturing_exporter(seen)
            )
        )

        assert data == b"rowrow"
        uow.establishment_dashboard_repo.stream_for_export.assert_called_once_with(
            establishment_id=establishment.id, params=params
        )
        # The export must never go through the paginated query.
        uow.establishment_dashboard_repo.get_subject_listing.assert_not_awaited()

    async def test_rows_are_built_into_listing_items(
        self, make_dashboard_uow, establishment
    ):
        uow = make_dashboard_uow()
        uow.establishment_dashboard_repo.stream_for_export = MagicMock(
            return_value=aiter_of([self._row(measurement_count=3)])
        )
        seen: list = []

        await drain(
            EstablishmentDashboardService(uow).export_establishment_subjects(
                establishment.id,
                EstablishmentSubjectListingParams(),
                capturing_exporter(seen),
            )
        )

        assert len(seen) == 1
        assert seen[0].measurement_count == 3
        assert seen[0].nutritional_status is not None


class TestBuildMapItem:
    def test_no_rows_means_no_data(self, make_establishment):
        establishment = make_establishment()
        item = EstablishmentDashboardService._build_map_item(establishment, [])
        assert item.has_data is False
        assert item.severity is None
        assert item.dominant_status is None

    def test_reuses_the_alert_status_rollup(self, make_establishment):
        """Same severity/dominant_status _build_alert_status would give the
        ficha -- this is what guarantees the map and the ficha never diverge.
        """
        establishment = make_establishment()
        rows = [_row(None, 1), _row(AlertType.SEVERELY_WASTED, 1)]
        item = EstablishmentDashboardService._build_map_item(establishment, rows)
        assert item.has_data is True
        assert item.severity == AlertSeverity.CRITICAL
        assert item.dominant_status == NutritionalStatus.SEVERELY_WASTED

    def test_carries_identity_and_location(self, make_establishment):
        establishment = make_establishment(name="Comedor X")
        item = EstablishmentDashboardService._build_map_item(establishment, [])
        assert item.id == establishment.id
        assert item.name == "Comedor X"
        assert item.latitude == establishment.latitude
        assert item.longitude == establishment.longitude


class TestGetEstablishmentsMap:
    pytestmark = pytest.mark.asyncio

    async def test_rows_are_grouped_by_establishment_not_mixed(
        self, make_establishment
    ):
        est_a = make_establishment(name="A")
        est_b = make_establishment(name="B")
        uow = AsyncMock()
        uow.establishment_repo.get_all = AsyncMock(return_value=[est_a, est_b])
        uow.establishment_dashboard_repo.get_status_distribution_for_all = AsyncMock(
            return_value=[
                SimpleNamespace(
                    establishment_id=est_a.id, alert_type=None, severity=None, count=2
                ),
                SimpleNamespace(
                    establishment_id=est_b.id,
                    alert_type=AlertType.OBESE,
                    severity=AlertSeverity.MEDIUM,
                    count=1,
                ),
            ]
        )

        items = await EstablishmentDashboardService(uow).get_establishments_map()

        by_id = {item.id: item for item in items}
        assert by_id[est_a.id].dominant_status == NutritionalStatus.NORMAL
        assert by_id[est_b.id].dominant_status == NutritionalStatus.OBESE

    async def test_establishment_with_no_matching_rows_still_appears(
        self, make_establishment
    ):
        """A bug that iterated the grouped rows instead of every establishment
        would silently drop this one -- exactly the CA3 failure mode."""
        est_with_data = make_establishment(name="Con datos")
        est_without_data = make_establishment(name="Sin datos")
        uow = AsyncMock()
        uow.establishment_repo.get_all = AsyncMock(
            return_value=[est_with_data, est_without_data]
        )
        uow.establishment_dashboard_repo.get_status_distribution_for_all = AsyncMock(
            return_value=[
                SimpleNamespace(
                    establishment_id=est_with_data.id,
                    alert_type=None,
                    severity=None,
                    count=1,
                )
            ]
        )

        items = await EstablishmentDashboardService(uow).get_establishments_map()

        by_id = {item.id: item for item in items}
        assert len(items) == 2
        assert by_id[est_without_data.id].has_data is False
