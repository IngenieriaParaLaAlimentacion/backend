import asyncio
from collections.abc import Callable
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config.settings import settings
from app.db.advisory_lock import try_advisory_lock
from app.db.database import engine
from app.db.unit_of_work import UnitOfWork
from app.exceptions.domain_exceptions import NotificationConfigurationError
from app.services.notifications.fcm_client import FcmClient
from app.services.notifications.stale_establishment_notification_service import (
    StaleEstablishmentNotificationService,
)

logger = structlog.get_logger()

ART = ZoneInfo("America/Argentina/Buenos_Aires")
ACTIVE_HOURS = "8-22"
SCHEDULER_JOB_ID = "stale-establishment-notifications"

# Stable application-specific bigint. Session advisory locks are released by PostgreSQL
# when a crashed process loses its connection.
_ADVISORY_LOCK_ID = 0x5354414C45505553


def build_stale_establishment_notification_service() -> (
    StaleEstablishmentNotificationService
):
    """Build the scheduled service without holding a database transaction open."""
    fcm_client = None
    if settings.has_fcm_credentials:
        assert settings.fcm_project_id is not None
        assert settings.fcm_client_email is not None
        assert settings.fcm_private_key is not None
        try:
            fcm_client = FcmClient(
                project_id=settings.fcm_project_id,
                client_email=settings.fcm_client_email,
                private_key=settings.fcm_private_key,
            )
        except ValueError as error:
            raise NotificationConfigurationError() from error
    return StaleEstablishmentNotificationService(
        uow_factory=UnitOfWork,
        fcm_client=fcm_client,
    )


class StaleEstablishmentScheduler:
    """Run stale-establishment notification processing inside FastAPI."""

    def __init__(
        self,
        *,
        database_engine: AsyncEngine = engine,
        service_factory: Callable[
            [], StaleEstablishmentNotificationService
        ] = build_stale_establishment_notification_service,
    ) -> None:
        self.database_engine = database_engine
        self.service_factory = service_factory
        self._idle = asyncio.Event()
        self._idle.set()
        self.scheduler = AsyncIOScheduler(timezone=ART)
        self.scheduler.add_job(
            self.run_once,
            trigger=CronTrigger(
                hour=ACTIVE_HOURS,
                minute=0,
                second=0,
                timezone=ART,
            ),
            id=SCHEDULER_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60 * 60,
        )

    def start(self) -> None:
        """Start hourly processing outside the 23:00-08:00 ART silent window."""
        self.scheduler.start()
        logger.info(
            "Stale-establishment scheduler started",
            timezone=str(ART),
            active_hours=ACTIVE_HOURS,
        )

    async def shutdown(self) -> None:
        """Stop scheduling new executions and wait for active work."""
        self.scheduler.pause()
        await self._idle.wait()
        self.scheduler.shutdown(wait=False)
        # AsyncIOScheduler enqueues its synchronous shutdown on the event loop.
        while self.scheduler.running:
            await asyncio.sleep(0)

    async def run_once(self) -> None:
        """Run once when this process wins cross-process database ownership."""
        self._idle.clear()
        try:
            async with try_advisory_lock(
                self.database_engine, _ADVISORY_LOCK_ID
            ) as acquired:
                if not acquired:
                    logger.info(
                        "Stale-establishment scheduler run skipped",
                        reason="another_process_owns_lock",
                    )
                    return

                logger.info("Stale-establishment scheduler run started")
                try:
                    await self.service_factory().run()
                except NotificationConfigurationError:
                    logger.error(
                        "Stale-establishment scheduler is not configured",
                        exc_info=True,
                    )
                    return
                except Exception:
                    logger.exception("Stale-establishment scheduler run failed")
                    raise
                logger.info("Stale-establishment scheduler run completed")
        finally:
            self._idle.set()
