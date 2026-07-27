import uuid
from datetime import date, datetime, timezone
from math import ceil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.measurement import AlertSeverity, AlertType, NutritionalStatus
from app.domain.pagination import PaginatedResult
from app.domain.subject import Sex, SubjectBase, SubjectDomain
from app.domain.subject_event import SubjectEventType
from app.exceptions.domain_exceptions import (
    EmptyUpdateRequestError,
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
    UniqueConstraintError,
)
from app.schemas.subject_schema import SubjectRequest, SubjectUpdateRequest
from app.services.subject_service import SubjectService


@pytest.fixture
def make_subject():
    """Return a factory that builds a mock Subject ORM instance."""

    def _make(
        dni: int = 12345678,
        sex: Sex = Sex.MALE,
        name: str = "Juan",
        last_name: str = "Perez",
        birth_date: date = date(2010, 1, 1),
        is_rural: bool = False,
        is_indigenous: bool = False,
    ):
        s = MagicMock()
        s.id = uuid.uuid4()
        s.dni = dni
        s.sex = sex
        s.name = name
        s.last_name = last_name
        s.birth_date = birth_date
        s.is_rural = is_rural
        s.is_indigenous = is_indigenous
        return s

    return _make


@pytest.fixture
def make_uow(make_subject):
    """Return a factory that builds a mock UnitOfWork for SubjectService."""

    def _make(listing=None, total=0, latest_measurement=None):
        uow = AsyncMock()
        uow.subject_repo.create = AsyncMock(return_value=make_subject())
        uow.subject_repo.get_subject_listing = AsyncMock(
            return_value=(listing or [], total)
        )
        # Defaults to "never measured". Without an explicit None an AsyncMock
        # would hand back a truthy mock and the detail builder would try to read
        # alerts off it.
        uow.measurement_repo.get_latest_for_subject = AsyncMock(
            return_value=latest_measurement
        )
        uow.subject_event_repo.append = AsyncMock()
        uow.commit = AsyncMock()
        return uow

    return _make


@pytest.fixture
def make_measurement():
    """Return a factory for an ORM-like Measurement with establishment and alerts."""

    def _make(alerts=None):
        establishment = MagicMock()
        establishment.id = uuid.uuid4()
        establishment.name = "Comedor Norte"
        establishment.city = "La Plata"
        establishment.province = "Buenos Aires"

        m = MagicMock()
        m.id = uuid.uuid4()
        m.measured_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
        m.weight_kg = 21.0
        m.height_cm = 118.0
        m.bmi = 15.08
        m.establishment = establishment
        m.alerts = alerts or []
        return m

    return _make


@pytest.fixture
def valid_request():
    return SubjectRequest(
        dni=12345678,
        sex=Sex.MALE,
        name="Juan",
        last_name="Perez",
        birth_date=date(2010, 1, 1),
        is_rural=False,
        is_indigenous=False,
    )


class TestCreateSubject:
    @pytest.mark.asyncio
    async def test_returns_subject_domain_and_commits(
        self, make_subject, make_uow, valid_request
    ):
        subject = make_subject()
        actor_id = uuid.uuid4()
        uow = make_uow()
        uow.subject_repo.create = AsyncMock(return_value=subject)
        service = SubjectService(uow)

        result, created = await service.create_subject(valid_request, actor_id=actor_id)

        assert created is True
        assert isinstance(result, SubjectDomain)
        assert result.id == subject.id
        assert result.dni == subject.dni
        uow.subject_event_repo.append.assert_called_once()
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_if_dni_already_exists(self, make_uow, valid_request):
        uow = make_uow()
        uow.subject_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("subject", (None, valid_request.dni))
        )
        uow.subject_repo.get_by_dni = AsyncMock(return_value=None)
        service = SubjectService(uow)

        with pytest.raises(SubjectAlreadyExistsError):
            await service.create_subject(valid_request, actor_id=uuid.uuid4())

        uow.subject_repo.create.assert_called_once()
        uow.subject_event_repo.append.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_type_is_subject_created(
        self, make_subject, make_uow, valid_request
    ):
        """append is always called with SUBJECT_CREATED, never another type."""
        uow = make_uow()
        subject = make_subject()
        actor_id = uuid.uuid4()
        uow.subject_repo.create = AsyncMock(return_value=subject)
        await SubjectService(uow).create_subject(valid_request, actor_id=actor_id)

        _, kwargs = uow.subject_event_repo.append.call_args
        assert kwargs["event_type"] == SubjectEventType.SUBJECT_CREATED
        assert kwargs["actor_id"] == actor_id
        assert kwargs["subject_id"] == subject.id

    @pytest.mark.asyncio
    async def test_replay_by_id_returns_existing_without_event(
        self, make_subject, make_uow
    ):
        """A request whose id already exists replays the stored subject (200)."""
        existing = make_subject()
        request = SubjectRequest(
            id=existing.id,
            dni=12345678,
            sex=Sex.MALE,
            name="Juan",
            last_name="Perez",
            birth_date=date(2010, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=existing)
        service = SubjectService(uow)

        result, created = await service.create_subject(request, actor_id=uuid.uuid4())

        assert created is False
        assert result.id == existing.id
        uow.subject_repo.create.assert_not_called()
        uow.subject_event_repo.append.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_id_race_on_conflict_replays_existing(self, make_subject, make_uow):
        """A concurrent insert of the same id surfaces as a replay, not a conflict."""
        raced = make_subject()
        request = SubjectRequest(
            id=raced.id,
            dni=12345678,
            sex=Sex.MALE,
            name="Juan",
            last_name="Perez",
            birth_date=date(2010, 1, 1),
            is_rural=False,
            is_indigenous=False,
        )
        uow = make_uow()
        # First pre-check misses; the row lands between the check and our insert.
        uow.subject_repo.get_by_id = AsyncMock(side_effect=[None, raced])
        uow.subject_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("subject", (raced.id, request.dni))
        )
        service = SubjectService(uow)

        result, created = await service.create_subject(request, actor_id=uuid.uuid4())

        assert created is False
        assert result.id == raced.id
        uow.subject_event_repo.append.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_dni_conflict_carries_canonical_subject(
        self, make_subject, make_uow, valid_request
    ):
        """A DNI collision raises with the canonical subject in the extensions."""
        canonical = make_subject(dni=valid_request.dni)
        uow = make_uow()
        uow.subject_repo.create = AsyncMock(
            side_effect=UniqueConstraintError("subject", (None, valid_request.dni))
        )
        uow.subject_repo.get_by_dni = AsyncMock(return_value=canonical)
        service = SubjectService(uow)

        with pytest.raises(SubjectAlreadyExistsError) as exc_info:
            await service.create_subject(valid_request, actor_id=uuid.uuid4())

        canonical_body = exc_info.value.extensions["canonical_subject"]
        assert canonical_body["id"] == str(canonical.id)
        assert canonical_body["dni"] == canonical.dni
        uow.subject_event_repo.append.assert_not_called()
        uow.commit.assert_not_called()


class TestGetSubject:
    @pytest.mark.asyncio
    async def test_returns_subject_domain(self, make_subject, make_uow):
        subject = make_subject()
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)
        service = SubjectService(uow)

        result = await service.get_subject(subject.id)

        assert isinstance(result, SubjectDomain)
        assert result.id == subject.id
        assert result.dni == subject.dni

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self, make_uow):
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=None)
        service = SubjectService(uow)

        with pytest.raises(SubjectNotFoundError):
            await service.get_subject(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_never_measured_subject_has_no_status(self, make_subject, make_uow):
        subject = make_subject()
        uow = make_uow(latest_measurement=None)
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)

        result = await SubjectService(uow).get_subject(subject.id)

        # None, not NORMAL: "never measured" is not a clinical reading.
        assert result.nutritional_status is None
        assert result.latest_measurement is None

    @pytest.mark.asyncio
    async def test_measured_subject_without_alerts_is_normal(
        self, make_subject, make_uow, make_measurement
    ):
        subject = make_subject()
        uow = make_uow(latest_measurement=make_measurement(alerts=[]))
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)

        result = await SubjectService(uow).get_subject(subject.id)

        assert result.nutritional_status == NutritionalStatus.NORMAL
        assert result.latest_measurement is not None

    @pytest.mark.asyncio
    async def test_status_is_derived_from_the_latest_alert(
        self, make_subject, make_uow, make_measurement
    ):
        alert = SimpleNamespace(
            id=uuid.uuid4(),
            measurement_id=uuid.uuid4(),
            alert_type=AlertType.WASTED,
            severity=AlertSeverity.HIGH,
            detail="...",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )
        subject = make_subject()
        uow = make_uow(latest_measurement=make_measurement(alerts=[alert]))
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)

        result = await SubjectService(uow).get_subject(subject.id)

        assert result.nutritional_status == NutritionalStatus.WASTED
        assert result.latest_measurement.alerts[0].alert_type == AlertType.WASTED

    @pytest.mark.asyncio
    async def test_latest_measurement_carries_its_establishment(
        self, make_subject, make_uow, make_measurement
    ):
        # The badge is the subject's global latest reading, so clients need to
        # know which comedor it came from to label it.
        subject = make_subject()
        uow = make_uow(latest_measurement=make_measurement())
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)

        result = await SubjectService(uow).get_subject(subject.id)

        assert result.latest_measurement.establishment.name == "Comedor Norte"
        assert result.latest_measurement.bmi == 15.08


class TestGetSubjectsPaginated:
    @pytest.mark.asyncio
    async def test_returns_items(self, make_subject, make_uow):
        subjects = [make_subject(), make_subject()]
        service = SubjectService(uow=make_uow(listing=subjects, total=2))

        result = await service.get_subject_listing(page=1, page_size=20, search=None)

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 2
        assert result.page == 1
        assert result.page_size == 20

    @pytest.mark.asyncio
    async def test_calculates_total_pages(self, make_subject, make_uow):
        subjects = [make_subject() for _ in range(5)]
        service = SubjectService(uow=make_uow(listing=subjects, total=23))

        result = await service.get_subject_listing(page=1, page_size=5, search=None)

        assert result.total_pages == ceil(23 / 5)

    @pytest.mark.asyncio
    async def test_empty(self, make_uow):
        service = SubjectService(uow=make_uow([], total=0))

        result = await service.get_subject_listing(page=1, page_size=20, search=None)

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_passes_correct_offset(self, make_uow):
        uow = make_uow([], total=0)
        service = SubjectService(uow=uow)

        await service.get_subject_listing(page=3, page_size=10, search=None)

        uow.subject_repo.get_subject_listing.assert_called_once_with(
            limit=10, offset=20, search=None
        )

    @pytest.mark.asyncio
    async def test_items_are_schema_instances(self, make_subject, make_uow):
        subjects = [make_subject()]
        service = SubjectService(uow=make_uow(listing=subjects, total=1))

        result = await service.get_subject_listing(page=1, page_size=20, search=None)

        assert all(isinstance(item, SubjectBase) for item in result.items)

    @pytest.mark.asyncio
    async def test_forwards_search_to_repo(self, make_uow):
        uow = make_uow([], total=0)
        service = SubjectService(uow=uow)

        await service.get_subject_listing(page=1, page_size=20, search="Subject search")

        uow.subject_repo.get_subject_listing.assert_called_once_with(
            limit=20,
            offset=0,
            search="Subject search",
        )

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_search(self, make_uow):
        uow = make_uow([], total=0)
        service = SubjectService(uow=uow)

        await service.get_subject_listing(
            page=1, page_size=20, search="    Subject search     "
        )

        uow.subject_repo.get_subject_listing.assert_called_once_with(
            limit=20,
            offset=0,
            search="Subject search",
        )

    @pytest.mark.asyncio
    async def test_whitespace_only_search_passes_none(self, make_uow):
        uow = make_uow([], total=0)
        service = SubjectService(uow=uow)

        await service.get_subject_listing(page=1, page_size=20, search="       ")

        uow.subject_repo.get_subject_listing.assert_called_once_with(
            limit=20,
            offset=0,
            search=None,
        )


class TestUpdateSubject:
    @pytest.mark.asyncio
    async def test_raises_if_empty_update(self, make_uow):
        """An empty body is rejected before hitting the DB."""
        uow = make_uow()
        service = SubjectService(uow)

        with pytest.raises(EmptyUpdateRequestError):
            await service.update_subject(
                uuid.uuid4(), SubjectUpdateRequest(), actor_id=uuid.uuid4()
            )

        uow.subject_repo.get_by_id.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_subject_not_found(self, make_uow):
        """SubjectNotFoundError is raised when the subject does not exist."""
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=None)
        service = SubjectService(uow)

        with pytest.raises(SubjectNotFoundError):
            await service.update_subject(
                uuid.uuid4(), SubjectUpdateRequest(name="Carlos"), actor_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_if_dni_conflict(self, make_subject, make_uow):
        """SubjectAlreadyExistsError is raised when the new DNI belongs
        to another subject."""
        subject = make_subject()
        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)
        uow.subject_repo.update = AsyncMock(
            side_effect=UniqueConstraintError("dni", 99999999)
        )
        service = SubjectService(uow)

        with pytest.raises(SubjectAlreadyExistsError):
            await service.update_subject(
                subject.id, SubjectUpdateRequest(dni=99999999), actor_id=uuid.uuid4()
            )

        uow.subject_event_repo.append.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_payload_contains_before_and_after(
        self, make_subject, make_uow
    ):
        """The SUBJECT_UPDATED event payload reflects exactly the changed fields."""
        subject = make_subject(name="Juan")
        updated = make_subject(name="Carlos")
        updated.id = subject.id

        uow = make_uow()
        uow.subject_repo.get_by_id = AsyncMock(return_value=subject)
        uow.subject_repo.update = AsyncMock(return_value=updated)
        service = SubjectService(uow)

        await service.update_subject(
            subject.id, SubjectUpdateRequest(name="Carlos"), actor_id=uuid.uuid4()
        )

        _, kwargs = uow.subject_event_repo.append.call_args
        assert kwargs["event_type"] == SubjectEventType.SUBJECT_UPDATED
        assert kwargs["payload"].before == {"name": "Juan"}
        assert kwargs["payload"].after == {"name": "Carlos"}
        uow.commit.assert_called_once()
