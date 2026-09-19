import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions.domain_exceptions import NotificationConfigurationError
from app.services.notifications.stale_establishment_scheduler import (
    ART,
    SCHEDULER_JOB_ID,
    StaleEstablishmentScheduler,
    build_stale_establishment_notification_service,
)


def test_schedule_runs_hourly_from_08_through_22_art():
    scheduler = StaleEstablishmentScheduler(database_engine=object())
    job = scheduler.scheduler.get_job(SCHEDULER_JOB_ID)

    assert job is not None
    assert str(job.trigger) == "cron[hour='8-22', minute='0', second='0']"
    after_last_run = datetime(2026, 9, 19, 22, 0, 1, tzinfo=ART)
    assert job.trigger.get_next_fire_time(None, after_last_run) == datetime(
        2026, 9, 20, 8, 0, 0, tzinfo=ART
    )


@pytest.mark.asyncio
async def test_scheduler_starts_and_stops_on_the_running_event_loop():
    scheduler = StaleEstablishmentScheduler(database_engine=object())

    scheduler.start()
    assert scheduler.scheduler.running is True

    await scheduler.shutdown()
    assert scheduler.scheduler.running is False


@pytest.mark.asyncio
async def test_run_once_executes_service_when_database_lock_is_acquired():
    service = AsyncMock()

    @asynccontextmanager
    async def acquired_lock(*args, **kwargs):
        yield True

    scheduler = StaleEstablishmentScheduler(
        database_engine=object(), service_factory=lambda: service
    )
    with patch(
        "app.services.notifications.stale_establishment_scheduler.try_advisory_lock",
        acquired_lock,
    ):
        await scheduler.run_once()

    service.run.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_run_once_skips_when_another_process_owns_database_lock():
    service_factory = AsyncMock()

    @asynccontextmanager
    async def unavailable_lock(*args, **kwargs):
        yield False

    scheduler = StaleEstablishmentScheduler(
        database_engine=object(), service_factory=service_factory
    )
    with patch(
        "app.services.notifications.stale_establishment_scheduler.try_advisory_lock",
        unavailable_lock,
    ):
        await scheduler.run_once()

    service_factory.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_pauses_new_runs_and_waits_for_active_run():
    scheduler = StaleEstablishmentScheduler(database_engine=object())
    apscheduler = MagicMock()
    apscheduler.running = True
    apscheduler.shutdown.side_effect = lambda **kwargs: setattr(
        apscheduler, "running", False
    )
    scheduler.scheduler = apscheduler
    scheduler._idle.clear()

    shutdown = asyncio.create_task(scheduler.shutdown())
    await asyncio.sleep(0)

    apscheduler.pause.assert_called_once_with()
    assert shutdown.done() is False

    scheduler._idle.set()
    await shutdown
    apscheduler.shutdown.assert_called_once_with(wait=False)


def test_malformed_fcm_credentials_raise_canonical_configuration_error():
    with (
        patch(
            "app.services.notifications.stale_establishment_scheduler.settings.fcm_project_id",
            "project",
        ),
        patch(
            "app.services.notifications.stale_establishment_scheduler.settings.fcm_client_email",
            "sender@example.test",
        ),
        patch(
            "app.services.notifications.stale_establishment_scheduler.settings.fcm_private_key",
            "not-a-private-key",
        ),
        patch(
            "app.services.notifications.stale_establishment_scheduler.FcmClient",
            side_effect=ValueError("malformed"),
        ),
    ):
        with pytest.raises(NotificationConfigurationError):
            build_stale_establishment_notification_service()
