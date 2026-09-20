import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.core.interfaces.unit_of_work import IUnitOfWork
from app.exceptions.domain_exceptions import NotificationConfigurationError
from app.services.notifications.fcm_client import FcmClient, FcmOutcome

_FIRST_THRESHOLD_HOURS = 168
_NEXT_THRESHOLD = {168: 336, 336: 504, 504: None}
_LEASE = timedelta(minutes=2)
_BATCH_SIZE = 10
_MAX_JOBS_PER_RUN = 500
_DUE_CYCLE_LIMIT = 100


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StaleEstablishmentNotificationService:
    """Create and dispatch the three inactivity notifications."""

    def __init__(
        self,
        uow_factory: Callable[[], IUnitOfWork],
        fcm_client: FcmClient | None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.uow_factory = uow_factory
        self.fcm_client = fcm_client
        self.clock = clock

    def _configuration(self) -> FcmClient:
        if self.fcm_client is None:
            raise NotificationConfigurationError()
        return self.fcm_client

    @staticmethod
    def _message(stale_days: int) -> tuple[str, str]:
        return (
            f"Hace {stale_days} días que no se registran salidas",
            "Registrá una salida para mantener actualizado el stock.",
        )

    async def _synchronize_cycles(self) -> None:
        """Create/reset current cycles from strictly newer event-time maxima."""
        async with self.uow_factory() as uow:
            advances = await uow.stale_cycle_repo.list_activity_advances()
            for activity in advances:
                latest = activity.last_outflow_at.astimezone(timezone.utc)
                cycle = await uow.stale_cycle_repo.get_for_update(
                    activity.establishment_id
                )
                started_at = latest
                first_due_at = started_at + timedelta(hours=_FIRST_THRESHOLD_HOURS)
                if cycle is None:
                    cycle = await uow.stale_cycle_repo.create_if_absent(
                        establishment_id=activity.establishment_id,
                        last_outflow_at=latest,
                        started_at=started_at,
                        next_threshold_hours=_FIRST_THRESHOLD_HOURS,
                        next_due_at=first_due_at,
                    )
                    if cycle is None:
                        cycle = await uow.stale_cycle_repo.get_for_update(
                            activity.establishment_id
                        )
                if cycle is not None and latest > cycle.last_outflow_at:
                    await uow.stale_cycle_repo.delete_pending_jobs(cycle.id)
                    cycle.last_outflow_at = latest
                    cycle.started_at = started_at
                    cycle.next_threshold_hours = _FIRST_THRESHOLD_HOURS
                    cycle.next_due_at = first_due_at
            await uow.commit()

    async def _consume_due_thresholds(self, *, now: datetime) -> None:
        """Create jobs and advance no more than one threshold per due cycle."""
        async with self.uow_factory() as uow:
            after_due_at = None
            after_id = None
            eligible = []
            while len(eligible) < _DUE_CYCLE_LIMIT:
                cycles = await uow.stale_cycle_repo.list_due_for_update(
                    now=now,
                    limit=_DUE_CYCLE_LIMIT,
                    after_due_at=after_due_at,
                    after_id=after_id,
                )
                if not cycles:
                    break
                # Capture the keyset cursor before advancing any cycle in this page.
                after_due_at = cycles[-1].next_due_at
                after_id = cycles[-1].id
                for cycle in cycles:
                    devices = (
                        await uow.push_device_repo.list_eligible_for_establishment(
                            cycle.establishment_id
                        )
                    )
                    if not devices:
                        continue
                    eligible.append((cycle, devices))
                    if len(eligible) == _DUE_CYCLE_LIMIT:
                        break
                if len(cycles) < _DUE_CYCLE_LIMIT:
                    break
            for cycle, devices in eligible:
                threshold = cycle.next_threshold_hours
                assert threshold is not None
                await uow.push_delivery_job_repo.create_for_devices(
                    stale_cycle_id=cycle.id,
                    threshold_hours=threshold,
                    device_ids=[device.id for device in devices],
                    available_at=now,
                )
                next_threshold = _NEXT_THRESHOLD[threshold]
                cycle.next_threshold_hours = next_threshold
                cycle.next_due_at = (
                    None
                    if next_threshold is None
                    else cycle.started_at + timedelta(hours=next_threshold)
                )
            await uow.commit()

    @staticmethod
    def _retry_delay(attempt_count: int) -> timedelta:
        seconds = min(60 * (2 ** max(attempt_count - 1, 0)), 6 * 60 * 60)
        return timedelta(seconds=seconds)

    async def _claim(self, now: datetime, limit: int):
        async with self.uow_factory() as uow:
            job_ids = await uow.push_delivery_job_repo.claim_due(
                now=now,
                claimed_until=now + _LEASE,
                limit=limit,
            )
            await uow.commit()
        if not job_ids:
            return []
        async with self.uow_factory() as uow:
            return await uow.push_delivery_job_repo.get_contexts(job_ids)

    async def _finish(self, job, outcome: FcmOutcome, now: datetime) -> None:
        async with self.uow_factory() as uow:
            if outcome == FcmOutcome.TRANSIENT:
                await uow.push_delivery_job_repo.release_for_retry(
                    job.job_id,
                    available_at=now + self._retry_delay(job.attempt_count),
                )
            else:
                if outcome == FcmOutcome.PERMANENT_TOKEN:
                    await uow.push_device_repo.delete_if_token_matches(
                        device_id=job.device_id,
                        fcm_token=job.fcm_token,
                    )
                await uow.push_delivery_job_repo.delete_by_id(job.job_id)
            await uow.commit()

    async def _send(self, fcm_client: FcmClient, job) -> FcmOutcome:
        stale_days = job.threshold_hours // 24
        title, body = self._message(stale_days)
        try:
            result = await fcm_client.send(
                token=job.fcm_token,
                title=title,
                body=body,
                data={
                    "type": "stale_establishment",
                    "establishment_id": str(job.establishment_id),
                    "stale_days": str(stale_days),
                },
                collapse_key=f"stale-establishment:{job.establishment_id}",
            )
            return result.outcome
        except Exception:
            return FcmOutcome.TRANSIENT

    async def _finalize_wave(self, jobs, outcomes) -> None:
        async def finalize(job, outcome) -> None:
            finished_at = self.clock().astimezone(timezone.utc)
            await self._finish(job, outcome, finished_at)

        results = await asyncio.gather(
            *(
                finalize(job, outcome)
                for job, outcome in zip(jobs, outcomes, strict=True)
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def run(self, now: datetime | None = None) -> None:
        """Enqueue due notices, then drain a bounded set of durable jobs."""
        fcm_client = self._configuration()
        current = (now or self.clock()).astimezone(timezone.utc)
        await self._synchronize_cycles()
        await self._consume_due_thresholds(now=current)

        try:
            await fcm_client.start()
            remaining = _MAX_JOBS_PER_RUN
            while remaining:
                claimed_at = self.clock().astimezone(timezone.utc)
                jobs = await self._claim(
                    claimed_at, min(_BATCH_SIZE, remaining)
                )
                if not jobs:
                    break
                outcomes = await asyncio.gather(
                    *(self._send(fcm_client, job) for job in jobs)
                )
                await self._finalize_wave(jobs, outcomes)
                remaining -= len(jobs)
        finally:
            await fcm_client.aclose()
