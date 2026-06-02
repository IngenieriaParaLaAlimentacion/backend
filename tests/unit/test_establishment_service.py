import uuid
from math import ceil
from unittest.mock import AsyncMock

import pytest

from app.domain.establishment import EstablishmentDomain
from app.domain.pagination import PaginatedResult
from app.exceptions.domain_exceptions import (
    EstablishmentAlreadyExistsError,
    EstablishmentNotFoundError,
)
from app.schemas.establishment_schema import (
    EstablishmentRequest,
    EstablishmentResponse,
    EstablishmentUpdateRequest,
)
from app.services.establishment_service import EstablishmentService


class TestEstablishmentResponse:
    def test_from_orm(self, make_establishment):
        orm = make_establishment(name="Centro B", address="Calle 2")
        response = EstablishmentResponse.model_validate(orm)

        assert response.id == orm.id
        assert response.name == "Centro B"
        assert response.address == "Calle 2"


class TestGetEstablishmentsPaginated:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def make_uow(self):
        def _make(establishments, total):
            uow = AsyncMock()
            uow.__aenter__.return_value = uow
            uow.establishment_repo.get_paginated = AsyncMock(
                return_value=(establishments, total)
            )
            return uow

        return _make

    async def test_returns_items(self, make_establishment, make_uow):
        establishments = [make_establishment(), make_establishment()]
        service = EstablishmentService(uow=make_uow(establishments, total=2))

        result = await service.get_establishments_paginated(
            page=1, page_size=20, search=None
        )

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 2
        assert result.page == 1
        assert result.page_size == 20

    async def test_calculates_total_pages(self, make_establishment, make_uow):
        establishments = [make_establishment() for _ in range(5)]
        service = EstablishmentService(uow=make_uow(establishments, total=23))

        result = await service.get_establishments_paginated(
            page=1, page_size=5, search=None
        )

        assert result.total_pages == ceil(23 / 5)

    async def test_empty(self, make_uow):
        service = EstablishmentService(uow=make_uow([], total=0))

        result = await service.get_establishments_paginated(
            page=1, page_size=20, search=None
        )

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    async def test_passes_correct_offset(self, make_uow):
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)

        await service.get_establishments_paginated(page=3, page_size=10, search=None)

        uow.establishment_repo.get_paginated.assert_called_once_with(
            limit=10, offset=20, search=None
        )

    async def test_items_are_schema_instances(self, make_establishment, make_uow):
        establishments = [make_establishment()]
        service = EstablishmentService(uow=make_uow(establishments, total=1))

        result = await service.get_establishments_paginated(
            page=1, page_size=20, search=None
        )

        assert all(isinstance(item, EstablishmentDomain) for item in result.items)

    async def test_forwards_search_to_repo(self, make_uow):
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)

        await service.get_establishments_paginated(
            page=1, page_size=20, search="Establishment search"
        )

        uow.establishment_repo.get_paginated.assert_called_once_with(
            limit=20,
            offset=0,
            search="Establishment search",
        )

    async def test_strips_whitespace_from_search(self, make_uow):
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)

        await service.get_establishments_paginated(
            page=1, page_size=20, search="    Establishment search     "
        )

        uow.establishment_repo.get_paginated.assert_called_once_with(
            limit=20,
            offset=0,
            search="Establishment search",
        )

    async def test_whitespace_only_search_passes_none(self, make_uow):
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)

        await service.get_establishments_paginated(
            page=1, page_size=20, search="       "
        )

        uow.establishment_repo.get_paginated.assert_called_once_with(
            limit=20,
            offset=0,
            search=None,
        )


class TestCreateEstablishment:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def make_uow(self, make_establishment):
        def _make(existing=None):
            uow = AsyncMock()
            uow.establishment_repo.get_by_data = AsyncMock(return_value=existing)
            uow.establishment_repo.create = AsyncMock(return_value=make_establishment())
            uow.commit = AsyncMock()
            return uow

        return _make

    async def test_raises_when_already_exists(self, make_uow, make_establishment):
        """Raises EstablishmentAlreadyExistsError when name+address is taken."""
        uow = make_uow(existing=make_establishment())
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentAlreadyExistsError):
            await service.create_establishment(
                EstablishmentRequest(name="Centro A", address="Calle 1"),
                actor_id=uuid.uuid4(),
            )

    async def test_calls_repo_create_when_no_duplicate(self, make_uow):
        """Delegates to the repo with the correct name and address."""
        uow = make_uow(existing=None)
        service = EstablishmentService(uow=uow)

        await service.create_establishment(
            EstablishmentRequest(name="Centro A", address="Calle 1"),
            actor_id=uuid.uuid4(),
        )

        uow.establishment_repo.create.assert_called_once_with(
            name="Centro A", address="Calle 1"
        )

    async def test_returns_created_establishment(self, make_uow, make_establishment):
        """Returns exactly what the repo returns."""
        expected = make_establishment(name="Centro A", address="Calle 1")
        uow = make_uow(existing=None)
        uow.establishment_repo.create = AsyncMock(return_value=expected)
        service = EstablishmentService(uow=uow)

        result = await service.create_establishment(
            EstablishmentRequest(name="Centro A", address="Calle 1"),
            actor_id=uuid.uuid4(),
        )

        assert result is expected


class TestGetEstablishmentById:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def make_uow(self, make_establishment):
        def _make(found=None):
            uow = AsyncMock()
            uow.establishment_repo.get_by_id = AsyncMock(return_value=found)
            return uow

        return _make

    async def test_returns_establishment_when_found(self, make_uow, make_establishment):
        """Returns the ORM object when the repo finds it."""
        expected = make_establishment()
        uow = make_uow(found=expected)
        service = EstablishmentService(uow=uow)

        result = await service.get_establishment_by_id(expected.id)

        assert result is expected

    async def test_raises_when_not_found(self, make_uow):
        """Raises EstablishmentNotFoundError when the repo returns None."""
        uow = make_uow(found=None)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentNotFoundError):
            await service.get_establishment_by_id(uuid.uuid4())


class TestUpdateEstablishment:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def make_uow(self, make_establishment):
        def _make(found=None, duplicate=None):
            uow = AsyncMock()
            uow.establishment_repo.get_by_id = AsyncMock(return_value=found)
            uow.establishment_repo.get_by_data = AsyncMock(return_value=duplicate)
            uow.establishment_repo.update = AsyncMock(side_effect=lambda est, **_: est)
            uow.commit = AsyncMock()
            return uow

        return _make

    async def test_raises_when_not_found(self, make_uow):
        """Raises EstablishmentNotFoundError when the ID does not exist."""
        uow = make_uow(found=None)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentNotFoundError):
            await service.update_establishment(
                uuid.uuid4(), EstablishmentUpdateRequest(name="Nuevo")
            )

    async def test_raises_when_duplicate_belongs_to_other(
        self, make_uow, make_establishment
    ):
        """Raises EstablishmentAlreadyExistsError when the resulting name+address
        is already taken by a different establishment."""
        existing = make_establishment(name="Centro A", address="Calle 1")
        other = make_establishment(name="Centro B", address="Calle 2")
        uow = make_uow(found=existing, duplicate=other)
        service = EstablishmentService(uow=uow)

        with pytest.raises(EstablishmentAlreadyExistsError):
            await service.update_establishment(
                existing.id,
                EstablishmentUpdateRequest(name="Centro B", address="Calle 2"),
            )

    async def test_allows_same_values_as_self(self, make_uow, make_establishment):
        """No error when the resulting name+address matches the same establishment."""
        existing = make_establishment(name="Centro A", address="Calle 1")
        uow = make_uow(found=existing, duplicate=existing)
        service = EstablishmentService(uow=uow)

        result = await service.update_establishment(
            existing.id,
            EstablishmentUpdateRequest(name="Centro A", address="Calle 1"),
        )

        assert result is existing

    async def test_calls_repo_update_with_correct_args(
        self, make_uow, make_establishment
    ):
        """Delegates to repo.update with the establishment object and patch data."""
        existing = make_establishment()
        uow = make_uow(found=existing, duplicate=None)
        service = EstablishmentService(uow=uow)

        await service.update_establishment(
            existing.id, EstablishmentUpdateRequest(name="Nuevo")
        )

        uow.establishment_repo.update.assert_called_once_with(
            existing, name="Nuevo", address=None
        )
