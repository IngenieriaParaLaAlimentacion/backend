from math import ceil
from unittest.mock import AsyncMock

import pytest

from app.domain.establishment import EstablishmentDomain
from app.domain.pagination import PaginatedResult
from app.schemas.establishment_schema import EstablishmentResponse
from app.services.establishment_service import EstablishmentService


@pytest.fixture
def make_uow():
    def _make(establishments, total):
        uow = AsyncMock()
        uow.__aenter__.return_value = uow
        uow.establishment_repo.get_paginated = AsyncMock(
            return_value=(establishments, total)
        )
        return uow

    return _make


class TestEstablishmentResponse:
    def test_from_orm(self, make_establishment):
        orm = make_establishment(name="Centro B", address="Calle 2")
        response = EstablishmentResponse.model_validate(orm)

        assert response.id == orm.id
        assert response.name == "Centro B"
        assert response.address == "Calle 2"


class TestGetEstablishmentsPaginated:
    @pytest.mark.asyncio
    async def test_returns_items(self, make_establishment, make_uow):
        establishments = [make_establishment(), make_establishment()]
        service = EstablishmentService(uow=make_uow(establishments, total=2))

        result = await service.get_establishments_paginated(page=1, page_size=20)

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 2
        assert result.total == 2
        assert result.page == 1
        assert result.page_size == 20

    @pytest.mark.asyncio
    async def test_calculates_total_pages(self, make_establishment, make_uow):
        establishments = [make_establishment() for _ in range(5)]
        service = EstablishmentService(uow=make_uow(establishments, total=23))

        result = await service.get_establishments_paginated(page=1, page_size=5)

        assert result.total_pages == ceil(23 / 5)

    @pytest.mark.asyncio
    async def test_empty(self, make_uow):
        service = EstablishmentService(uow=make_uow([], total=0))

        result = await service.get_establishments_paginated(page=1, page_size=20)

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0

    @pytest.mark.asyncio
    async def test_passes_correct_offset(self, make_uow):
        uow = make_uow([], total=0)
        service = EstablishmentService(uow=uow)

        await service.get_establishments_paginated(page=3, page_size=10)

        uow.establishment_repo.get_paginated.assert_called_once_with(
            limit=10, offset=20
        )

    @pytest.mark.asyncio
    async def test_items_are_schema_instances(self, make_establishment, make_uow):
        establishments = [make_establishment()]
        service = EstablishmentService(uow=make_uow(establishments, total=1))

        result = await service.get_establishments_paginated(page=1, page_size=20)

        assert all(isinstance(item, EstablishmentDomain) for item in result.items)
