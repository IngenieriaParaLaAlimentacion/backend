import uuid
from datetime import date
from math import ceil
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.pagination import PaginatedResult
from app.domain.subject import Sex, SubjectBase, SubjectDomain
from app.domain.subject_event import SubjectEventType
from app.exceptions.domain_exceptions import (
    SubjectAlreadyExistsError,
    SubjectNotFoundError,
)
from app.schemas.subject_schema import SubjectRequest
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

    def _make(existing_subject=None, listing=None, total=0):
        uow = AsyncMock()
        uow.subject_repo.get_by_dni = AsyncMock(return_value=existing_subject)
        uow.subject_repo.create = AsyncMock(return_value=make_subject())
        uow.subject_repo.get_subject_listing = AsyncMock(
            return_value=(listing or [], total)
        )
        uow.subject_event_repo.append = AsyncMock()
        uow.commit = AsyncMock()
        return uow

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

        result = await service.create_subject(valid_request, actor_id=actor_id)

        assert isinstance(result, SubjectDomain)
        assert result.id == subject.id
        assert result.dni == subject.dni
        uow.subject_event_repo.append.assert_called_once()
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_if_dni_already_exists(
        self, make_subject, make_uow, valid_request
    ):
        uow = make_uow(existing_subject=make_subject())
        service = SubjectService(uow)

        with pytest.raises(SubjectAlreadyExistsError):
            await service.create_subject(valid_request, actor_id=uuid.uuid4())

        uow.subject_repo.create.assert_not_called()
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
