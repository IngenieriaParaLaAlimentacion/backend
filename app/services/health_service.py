import asyncio

import structlog

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.exceptions.domain_exceptions import ServiceNotReadyError

logger = structlog.get_logger()


class HealthService:
    """Readiness checks for the dependencies the service needs to serve requests."""

    def __init__(self, uow: IUnitOfWork, db_timeout_seconds: float) -> None:
        self.uow = uow
        self.db_timeout_seconds = db_timeout_seconds

    async def check_readiness(self) -> dict[str, str]:
        """Return the outcome of each readiness check, by check name.

        Raises:
            ServiceNotReadyError: a check failed or did not finish within its
                timeout.
        """
        try:
            async with asyncio.timeout(self.db_timeout_seconds):
                await self.uow.health_repo.ping()
        except Exception:
            logger.warning("readiness_check_failed", check="database", exc_info=True)
            raise ServiceNotReadyError({"database": "unavailable"}) from None
        return {"database": "ok"}
