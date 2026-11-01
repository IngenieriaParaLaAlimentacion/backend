"""Readiness checks of HealthService."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.exceptions.domain_exceptions import ServiceNotReadyError
from app.services.health_service import HealthService


async def _hang() -> None:
    await asyncio.sleep(10)


async def test_readiness_fails_when_database_does_not_answer_in_time():
    uow = AsyncMock()
    uow.health_repo.ping = AsyncMock(side_effect=_hang)
    service = HealthService(uow, db_timeout_seconds=0.01)

    with pytest.raises(ServiceNotReadyError) as exc_info:
        await service.check_readiness()

    assert exc_info.value.extensions == {"checks": {"database": "unavailable"}}
