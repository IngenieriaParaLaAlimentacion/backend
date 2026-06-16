import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.establishment import UserEstablishmentStatus
from app.domain.measurement import AlertSeverity, AlertType, MeasurementDomain
from app.domain.subject import Sex
from app.domain.user import UserActor, UserRole
from app.exceptions.domain_exceptions import (
    EstablishmentNotFoundError,
    ForbiddenError,
    SubjectNotFoundError,
)
from app.schemas.measurement_schema import MeasurementRequest
from app.services.measurement_service import MeasurementService


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
    def _make(is_new: bool = True):
        m = MagicMock()
        m.id = uuid.uuid4()
        m.idempotency_key = uuid.uuid4()
        m.subject_id = uuid.uuid4()
        m.responsible_id = uuid.uuid4()
        m.establishment_id = uuid.uuid4()
        m.weight_kg = 70.0
        m.height_cm = 170.0
        m.bmi = 70.0 / (1.70**2)
        m.measured_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        m.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        return m, is_new

    return _make


@pytest.fixture
def make_alert_row():
    def _make(alert_type=AlertType.OVERWEIGHT, severity=AlertSeverity.MEDIUM):
        a = MagicMock()
        a.id = uuid.uuid4()
        a.measurement_id = uuid.uuid4()
        a.alert_type = alert_type
        a.severity = severity
        a.detail = "test detail"
        a.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        return a

    return _make


@pytest.fixture
def make_uow(make_subject, make_measurement):
    def _make(
        subject=None,
        establishment=MagicMock(),
        relation=None,
        measurement_result=None,
        alert_rows=None,
    ):
        uow = AsyncMock()
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject or make_subject())
        uow.establishment_repo.get_by_id = AsyncMock(return_value=establishment)
        uow.user_establishment_repo.get_relation = AsyncMock(return_value=relation)
        uow.measurement_repo.upsert_by_idempotency_key = AsyncMock(
            return_value=measurement_result or make_measurement()
        )
        uow.measurement_alert_repo.create_bulk = AsyncMock()
        uow.measurement_alert_repo.get_by_measurement_id = AsyncMock(
            return_value=alert_rows or []
        )
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
def manager_actor():
    return UserActor(user_id=uuid.uuid4(), role=UserRole.ESTABLISHMENT_MANAGER)


class TestRegisterValidation:
    @pytest.mark.asyncio
    async def test_raises_if_subject_not_found(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(subject=None)
        uow.subject_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(SubjectNotFoundError):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, admin_actor
            )

        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_establishment_not_found(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(establishment=None)

        with pytest.raises(EstablishmentNotFoundError):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, admin_actor
            )

        uow.commit.assert_not_called()


class TestEstablishmentAccessCheck:
    @pytest.mark.asyncio
    async def test_manager_with_no_relation_is_forbidden(
        self, make_uow, valid_request, manager_actor
    ):
        uow = make_uow(relation=None)

        with pytest.raises(ForbiddenError):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, manager_actor
            )

        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_manager_with_pending_relation_is_forbidden(
        self, make_uow, valid_request, manager_actor
    ):
        relation = MagicMock()
        relation.status = UserEstablishmentStatus.PENDING
        uow = make_uow(relation=relation)

        with pytest.raises(ForbiddenError):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, manager_actor
            )

    @pytest.mark.asyncio
    async def test_manager_with_approved_relation_succeeds(
        self, make_uow, valid_request, manager_actor
    ):
        relation = MagicMock()
        relation.status = UserEstablishmentStatus.APPROVED
        uow = make_uow(relation=relation)

        result = await MeasurementService(uow).register(
            uuid.uuid4(), valid_request, manager_actor
        )

        assert isinstance(result, MeasurementDomain)

    @pytest.mark.asyncio
    async def test_admin_skips_establishment_check(
        self, make_uow, valid_request, admin_actor
    ):
        uow = make_uow(relation=None)

        result = await MeasurementService(uow).register(
            uuid.uuid4(), valid_request, admin_actor
        )

        uow.user_establishment_repo.get_relation.assert_not_called()
        assert isinstance(result, MeasurementDomain)


class TestRegisterPersistence:
    @pytest.mark.asyncio
    async def test_new_measurement_with_alerts_calls_create_bulk(
        self, make_uow, make_subject, make_measurement, valid_request, admin_actor
    ):
        subject = make_subject(sex=Sex.MALE, birth_date=date(2000, 1, 1))
        measurement, _ = make_measurement(is_new=True)
        uow = make_uow(
            subject=subject,
            measurement_result=(measurement, True),
        )

        raw_alerts = [(AlertType.OVERWEIGHT, AlertSeverity.MEDIUM, "detail")]
        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.services.measurement_service.evaluate_alerts", return_value=raw_alerts
        ):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, admin_actor
            )

        uow.measurement_alert_repo.create_bulk.assert_called_once_with(
            measurement.id, raw_alerts
        )

    @pytest.mark.asyncio
    async def test_new_measurement_without_alerts_skips_create_bulk(
        self, make_uow, make_subject, make_measurement, valid_request, admin_actor
    ):
        subject = make_subject(sex=Sex.MALE, birth_date=date(2000, 1, 1))
        measurement, _ = make_measurement(is_new=True)
        uow = make_uow(subject=subject, measurement_result=(measurement, True))

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.services.measurement_service.evaluate_alerts", return_value=[]
        ):
            await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, admin_actor
            )

        uow.measurement_alert_repo.create_bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_replay_skips_alert_creation(
        self, make_uow, make_subject, make_measurement, valid_request, admin_actor
    ):
        subject = make_subject()
        measurement, _ = make_measurement()
        uow = make_uow(subject=subject, measurement_result=(measurement, False))

        await MeasurementService(uow).register(uuid.uuid4(), valid_request, admin_actor)

        uow.measurement_alert_repo.create_bulk.assert_not_called()

    @pytest.mark.asyncio
    async def test_commits_after_upsert(self, make_uow, valid_request, admin_actor):
        uow = make_uow()
        await MeasurementService(uow).register(uuid.uuid4(), valid_request, admin_actor)
        uow.commit.assert_called_once()


class TestRegisterReturnValue:
    @pytest.mark.asyncio
    async def test_returns_measurement_domain(
        self, make_uow, make_measurement, make_alert_row, valid_request, admin_actor
    ):
        measurement, _ = make_measurement()
        alert_row = make_alert_row()
        uow = make_uow(
            measurement_result=(measurement, True),
            alert_rows=[alert_row],
        )

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.services.measurement_service.evaluate_alerts", return_value=[]
        ):
            result = await MeasurementService(uow).register(
                uuid.uuid4(), valid_request, admin_actor
            )

        assert isinstance(result, MeasurementDomain)
        assert result.id == measurement.id
        assert result.bmi == measurement.bmi
        assert len(result.alerts) == 1
        assert result.alerts[0].alert_type == alert_row.alert_type
