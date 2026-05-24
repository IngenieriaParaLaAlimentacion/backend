import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.subject import Sex, SubjectDomain
from app.exceptions.domain_exceptions import SubjectAlreadyExistsError
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

    def _make(existing_subject=None):
        uow = AsyncMock()
        uow.subject_repo.get_by_dni = AsyncMock(return_value=existing_subject)
        uow.subject_repo.create = AsyncMock(return_value=make_subject())
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
        uow = make_uow()
        uow.subject_repo.create = AsyncMock(return_value=subject)
        service = SubjectService(uow)

        result = await service.create_subject(valid_request)

        assert isinstance(result, SubjectDomain)
        assert result.id == subject.id
        assert result.dni == subject.dni
        uow.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_if_dni_already_exists(
        self, make_subject, make_uow, valid_request
    ):
        uow = make_uow(existing_subject=make_subject())
        service = SubjectService(uow)

        with pytest.raises(SubjectAlreadyExistsError):
            await service.create_subject(valid_request)

        uow.subject_repo.create.assert_not_called()
        uow.commit.assert_not_called()
