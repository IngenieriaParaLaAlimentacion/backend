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
from app.exceptions.domain_exceptions import EstablishmentNotFoundError
from app.services.establishment_dashboard_service import EstablishmentDashboardService


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
def make_dashboard_uow(establishment):
    """Build an AsyncMock UnitOfWork wired for the dashboard repository."""

    def _make(
        metrics_row=None,
        distribution=None,
        measurement_count=0,
        subject_rows=None,
        subject_total=0,
        found=True,
    ):
        uow = AsyncMock()
        uow.establishment_repo.get_by_id = AsyncMock(
            return_value=establishment if found else None
        )
        uow.establishment_dashboard_repo.get_metrics = AsyncMock(
            return_value=metrics_row if metrics_row is not None else _metrics_row(0)
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
            await service.get_establishment_dashboard(uuid.uuid4())

    async def test_empty_establishment_reports_no_data(self, make_dashboard_uow):
        service = EstablishmentDashboardService(
            make_dashboard_uow(metrics_row=_metrics_row(0))
        )
        result = await service.get_establishment_dashboard(uuid.uuid4())

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
            uuid.uuid4()
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
            uuid.uuid4()
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
            uuid.uuid4()
        )
        assert result.metrics.avg_age_months == 77

    async def test_includes_the_establishment_identification(
        self, make_dashboard_uow, establishment
    ):
        uow = make_dashboard_uow(metrics_row=_metrics_row(0))
        result = await EstablishmentDashboardService(uow).get_establishment_dashboard(
            uuid.uuid4()
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
